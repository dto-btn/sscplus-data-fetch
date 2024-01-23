import glob
import json  # bourne
import logging
import os
import re
import time
from datetime import datetime

import azure.durable_functions as df
import azure.functions as func
import requests
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from azure.storage.fileshare import ShareServiceClient
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from langchain.chat_models import AzureChatOpenAI
from langchain.embeddings import AzureOpenAIEmbeddings
from llama_index import (Document, LLMPredictor, PromptHelper, ServiceContext,
                         StorageContext, VectorStoreIndex,
                         load_index_from_storage, set_global_service_context)
from llama_index.callbacks import CallbackManager, LlamaDebugHandler
from llama_index.llms import AzureOpenAI
from tenacity import retry, stop_after_attempt, wait_fixed

load_dotenv()

app = df.DFApp(http_auth_level=func.AuthLevel.FUNCTION)

connection_string   = os.getenv("StorageConnectionString")
blob_service_client = BlobServiceClient.from_connection_string(str(connection_string))

azure_openai_uri    = os.getenv("AzureOpenAIEndpoint")
api_key     = os.getenv("AzureOpenAIKey")
api_version = "2023-07-01-preview"

client = AzureOpenAI(
    engine="gpt4",
    api_version=api_version,
    azure_endpoint=azure_openai_uri,
    api_key=api_key
)

# make this configurable via a env variable ..
domain = "https://plus.ssc-spc.gc.ca"

@app.route(route="orchestrators/fetch_data")
@app.durable_client_input(client_name="client")
async def fetch_data(req: func.HttpRequest, client) -> func.HttpResponse:
    '''
    this durable client will fire the orchestrator to get all the ids
    necessary to do a data fetch from ssc plus drupal api
    and will store all the json payload in a azure blob storage
    '''

    # TODO: remove this later this is just a quick sanity check
    response = requests.get("https://ipinfo.io/ip")
    if response.status_code == 200:
        logging.info(f"Able to reach ipinfo.io/ip... External ip is: {response.text}")

    instance_id = await client.start_new("fetch_sscplus_data")
    response = client.create_check_status_response(req, instance_id)

    return response

# Orchestrator
@app.orchestration_trigger(context_name="context") #without a param the task is not properly registered..
def fetch_sscplus_data(context: df.DurableOrchestrationContext):

    #This will change in the future but the delta grab of ids is not yet implemented
    present_date = cutoffdate = datetime.now().strftime("%Y-%m-%d")
    pages = yield context.call_activity("get_all_ids", (present_date, cutoffdate))
    logging.info(f"There are {len(pages)} page(s) to process.")

    # compare ids against what has been downloaded so far. make a list of missing ids.
    download_pages_tasks = []
    for page in pages:
        blob_client = blob_service_client.get_blob_client("sscplusdata", page['blob_name'])
        if not blob_client.exists():
            download_pages_tasks.append(context.call_activity("download_page", page))
    # once we loop over the pages that do not exists in the storage, we task the function to download them.
    list_of_download = yield context.task_all(download_pages_tasks)

    return f"Finished downloading (or trying to ..): {len(download_pages_tasks)} page(s)"

# Activity
@app.activity_trigger(input_name="dates")
def get_all_ids(dates: tuple) -> list[dict]:
    """
    get all ids from the https://plus-test.ssc-spc.gc.ca/en/rest/all-ids call

    refine process so we can be more selective about the ids we retreive...
    produce a list that we will be looking at, specifically re-indexing a specific portion.
    •	/rest/updated-ids/week
      o	same
      o	updated with past 7 days
    •	/rest/updated-ids/month
      o	same
      o	updated within last 30 days
    """
    logging.info(f'Getting all page IDs. Cutoff date is {dates[1]}')
    pages = []

    try:
        r = _get_and_save(f"{domain}/en/rest/all-ids", f"ids-{dates[0]}.json")
        logging.info("Getting all ids that need to be processed...")
        for d in r:
            # add both pages here, en/fr versions
            pages.append({"id": d["nid"], "type": d["type"], "url": f"{domain}/en/rest/page-by-id/{d['nid']}", "blob_name": f"preload/{dates[0]}/{d['type']}/en/{d['nid']}.json"})
            pages.append({"id": d["nid"], "type": d["type"], "url": f"{domain}/fr/rest/page-by-id/{d['nid']}", "blob_name": f"preload/{dates[0]}/{d['type']}/fr/{d['nid']}.json"})
    except Exception as e:
        logging.error("Unable to send request and/or parse json. Error:" + str(e))
        return []

    return pages

# Activity
@app.activity_trigger(input_name="page")
def download_page(page: dict):
    """
    Will query the https://plus-test.ssc-spc.gc.ca/en/rest/page-by-id/336 API
    we make two separate calls, 1 for en and 1 for fr content.
    """
    try:
        logging.debug(f"Processing file id {page['id']}")
        _get_and_save(page['url'], page['blob_name'])
        return True
    except Exception as e:
        logging.error("Unable to download separate page file. Error:" + str(e))
        return False

# getting loads of connection terminated by fw or lb over their aks instances
# this helps greatly, but still need a net to catch missing ids.
@retry(stop=stop_after_attempt(5), wait=wait_fixed(3))
def _get_and_save(url, blob_name):
    response = requests.get(url, verify=False)
    blob_client = blob_service_client.get_blob_client("sscplusdata", blob_name)
    blob_client.upload_blob(json.dumps(response.json()).encode('utf-8'), overwrite=True)

    return response.json()

@app.route(route="orchestrators/durable_build_index")
@app.durable_client_input(client_name="client")
async def durable_build_index(req: func.HttpRequest, client) -> func.HttpResponse:
    '''
    build an index based on the date passed in parameter
    '''
    # get the parameter from the request
    date = req.params.get('date')

    if date:
        logging.info(f"Current date used: {date}")
        instance_id = await client.start_new("build_index_orc", None, date)
        response = client.create_check_status_response(req, instance_id)
        return response

    return func.HttpResponse(
            "No date provided",
            status_code=400
        )

# Orchestrator
@app.orchestration_trigger(context_name="context")
def build_index_orc(context: df.DurableOrchestrationContext):
    # Get the input data (date)
    date = context.get_input()
    pages = yield context.call_activity("load_pages_as_json", date)
    if pages is not None:
        yield context.call_activity("build_index", pages)
        return f"Finished creating index (with name: {date})!"

    return "failed to get date to start indexing .."

@app.activity_trigger(input_name="date")
def load_pages_as_json(date: str) -> list:
    logging.info("getting pages ...")
    return _get_pages_as_json("preload", date)

@app.activity_trigger(input_name="pages")
def build_index(pages: list) -> str:

    documents = []
    for page in pages:
        # https://gpt-index.readthedocs.io/en/v0.6.34/how_to/customization/custom_documents.html
        document = Document(
            text=str(page["body"]).replace("\n", " "),
            metadata={ # type: ignore
                'filename': page["filename"],
                'url': page["url"],
                'title': page["title"],
                'date': page["date"],
                'nid': page['nid']
            }
        )
        documents.append(document)

    logging.info("Finished loading all document in memory")

    """
    store documents into a vector store.
    note MS CognitiveSearchVectorStore:
        * https://learn.microsoft.com/en-us/azure/search/search-get-started-vector
        * https://gpt-index.readthedocs.io/en/stable/community/integrations/vector_stores.html#using-a-vector-store-as-an-index
    """
    set_global_service_context(_get_service_context("gpt-4", 8192))
    index = VectorStoreIndex.from_documents(documents)
    date = datetime.now().strftime("%Y-%m-%d")
    index.storage_context.persist(persist_dir="/tmp/storage/" + date)

    # writing files to Azure Storage
    container_client = blob_service_client.get_container_client("indices")
    for file in glob.glob(f"/tmp/storage/{date}/*"):
        blob_name = os.path.basename(file)
        blob_client = container_client.get_blob_client(date + "/" + blob_name)
        with open(file, "rb") as data:
            blob_client.upload_blob(data)

    return "Storage name: /tmp/storage/" + date

@app.schedule(schedule="0 0 * * 6", arg_name="timer", run_on_startup=True)
def get_page_updates(timer: func.TimerRequest) -> None:
    date = datetime.now().strftime("%Y-%m-%d")
    logging.info(' [rebuild index] Timed triggered function ran at %s', date)
    '''get updated pages since last week and store them'''
    try:
        r = _get_and_save(f"{domain}/en/rest/updated-ids/week", f"updated-ids-{date}.json")
        logging.info("Getting all ids that need to be processed...")
        for d in r:
            _get_and_save(f"{domain}/en/rest/page-by-id/{d['nid']}", f"updated/{date}/{d['type']}/en/{d['nid']}.json")
            _get_and_save(f"{domain}/fr/rest/page-by-id/{d['nid']}", f"updated/{date}/{d['type']}/fr/{d['nid']}.json")
    except Exception as e:
        logging.error("Unable to send request and/or parse json. Error:" + str(e))

    container_client = blob_service_client.get_container_client("indices")

    # Ensure the tmp directory exists
    os.makedirs('/tmp/latest', exist_ok=True)

    '''load index locally'''
    blob_list = container_client.list_blobs(name_starts_with="latest")
    for blob in blob_list:
        logging.info(f"CURRENT BLOB: {blob.name}")
        # Construct the full file path
        download_file_path = os.path.join('/tmp', blob.name)

         # Skip download if file already exists
        if os.path.exists(download_file_path):
            logging.info(f"File {download_file_path} already exists. Skipping download.")
            continue

        # Download the blob to a local file
        blob_client = container_client.get_blob_client(blob.name)
        with open(download_file_path, "wb") as download_file:
            download_file.write(blob_client.download_blob().readall())

    #TODO: reuse the all the files from above instead of re-loading them this way, inefficient.. might be useless to store them in the first place...
    pages = _get_pages_as_json("updated", date)
    nids_set = {str(page['nid']) for page in pages}

    '''load index in memory'''
    start = time.time()
    set_global_service_context(_get_service_context("gpt-4", 8192))
    storage_context = StorageContext.from_defaults(persist_dir=os.path.join("/tmp", "latest"))
    index = load_index_from_storage(storage_context=storage_context)
    end = time.time()
    logging.info("Took {} seconds to load index/storage context.".format(end-start))

    '''identify newly updated nodes and delete them, we will be re-building the new index and updating it instead..'''
    for k,v in storage_context.docstore.docs.items():
        filename = v.metadata['filename']
        match = re.search(r'(\d+)\.json$', filename)
        number = match.group(1) if match else None
        if number in nids_set:
            index.delete_ref_doc(k, delete_from_docstore=True)


    '''update the index with the new documents'''
    for page in pages:
        # https://gpt-index.readthedocs.io/en/v0.6.34/how_to/customization/custom_documents.html
        document = Document(
            text=str(page["body"]).replace("\n", " "),
            metadata={ # type: ignore
                'filename': page["filename"],
                'url': page["url"],
                'title': page["title"],
                'date': page["date"],
                'nid': page['nid']
            }
        )
        index.insert(document)

    '''persist the updated index'''
    index.storage_context.persist(persist_dir="/tmp/storage/latest")

    # writing files to Azure Storage
    container_client = blob_service_client.get_container_client("indices")
    for file in glob.glob(f"/tmp/storage/latest/*"):
        blob_name = os.path.basename(file)
        blob_client = container_client.get_blob_client("latest/" + blob_name)
        with open(file, "rb") as data:
            blob_client.upload_blob(data, overwrite=True)
    logging.info("done updating the index and re-uploading to storage")

def _get_service_context(model: str, context_window: int, num_output: int = 800, temperature: float = 0.7,) -> "ServiceContext":
    # using same dep as model name because of an older bug in langchains lib (now fixed I believe)
    llm = _get_llm(model, temperature)

    llm_predictor = _get_llm_predictor(llm)

    chunk_overlap_ratio = 0.1 # overlap for each token fragment
    prompt_helper = PromptHelper(context_window=context_window, num_output=num_output, chunk_overlap_ratio=chunk_overlap_ratio,)

    # limit is chunk size 1 atm
    embedding_llm = AzureOpenAIEmbeddings(
            model="text-embedding-ada-002", api_key=api_key, azure_endpoint=azure_openai_uri)

    llama_debug = LlamaDebugHandler(print_trace_on_end=True)
    callback_manager = CallbackManager([llama_debug])

    return ServiceContext.from_defaults(llm_predictor=llm_predictor, embed_model=embedding_llm, callback_manager=callback_manager, prompt_helper=prompt_helper)

def _get_llm(model: str, temperature: float = 0.7):
    return AzureChatOpenAI(model=model,
                           temperature=temperature,api_key=api_key, api_version=api_version, azure_endpoint=azure_openai_uri)

def _get_llm_predictor(llm) -> LLMPredictor:
    return LLMPredictor(llm=llm,)

def _get_pages_as_json(dir: str, date: str) -> list:
    pages = []
    container_client = blob_service_client.get_container_client("sscplusdata")
    blobs = container_client.list_blobs(dir + "/" + date + "/")

    ignore_selectors = ['div.comment-login-message', 'section.block-date-modified-block']

    for blob in blobs:
        blob_client = container_client.get_blob_client(blob) # type: ignore
        # Download the blob data and decode it to string
        data = blob_client.download_blob().readall().decode('utf-8')
        if data is not None:
            raw = json.loads(data)
            if isinstance(raw, list) and raw:
                raw = raw[0] # sometimes the object is boxed into an array, not useful to us
            if isinstance(raw, dict):
                page = {}
                soup = BeautifulSoup(raw["body"], "html.parser")
                # remove useless tags like date modified and login blocks (see example in 336 parsed data vs non parsed)
                for selector in ignore_selectors:
                     for s in soup.select(selector):
                         s.decompose()

                page["body"] = ' '.join(soup.stripped_strings)
                page["title"] = str(raw["title"]).strip()
                page["url"] = str(raw["url"]).strip()
                page["date"] = str(raw["date"]).strip()
                page["filename"] = blob_client.blob_name
                page["nid"] = str(raw['nid']).strip()

                pages.append(page)
    return pages

@app.schedule(schedule="0 0 * * 0", arg_name="timer", run_on_startup=True)
def update_index_and_restart_containers(timer: func.TimerRequest) -> None:
    """ Copy latest index to a fileshare used by the chatbot and then restart all the containers so they reload the index"""
    service = ShareServiceClient.from_connection_string(conn_str=str(os.getenv("FILESHARE_CONNECTION_STRING")))
    share_client = service.get_share_client(share=str(os.getenv("FILESHARE_NAME")))

    container_client = blob_service_client.get_container_client("indices")
    for blob in container_client.list_blobs("latest/"):
        blob_name = blob.name
        blob_client = container_client.get_blob_client(blob=blob_name)
        download_stream = blob_client.download_blob()
        file_client = share_client.get_file_client(file_path=blob_name)
        file_client.upload_file(download_stream) # type: ignore

    try:  
        credential = DefaultAzureCredential()
        token = credential.get_token("https://management.azure.com/.default")
        headers = {"Authorization": f"Bearer {token.token}"}
        # Use the token as needed...
    except Exception as e:
        # Log the error
        logging.error(f"An error occurred while getting the token: {e}")
        return None
    
    # # Construct the URL to restart the container app
    # POST https://management.azure.com/subscriptions/{subscriptionId}/resourceGroups/{resourceGroupName}/providers/Microsoft.ContainerInstance/containerGroups/{containerGroupName}/restart?api-version=2023-05-01
    subscriptionId = os.getenv("CONTAINER_SUB_ID")
    resourceGroupName = os.getenv("CONTAINER_RG_NAME")
    containerAppName = os.getenv("CONTAINER_APP_NAME")
    url_stop = f"https://management.azure.com/subscriptions/{subscriptionId}/resourceGroups/{resourceGroupName}/providers/Microsoft.App/containerApps/{containerAppName}/stop?api-version=2023-08-01-preview"
    logging.info(f"about to request to {url_stop}")
    # Make the POST request to stop the container app
    response_stop = requests.post(url_stop, headers=headers)
    logging.info("request made ...")
    logging.info(response_stop.status_code)
    # Check the response
    if response_stop.status_code == 202:
        logging.info(f'Stop command sent to container app: {containerAppName}')
        # Azure may provide an Azure-AsyncOperation header with a URL to poll for operation status
        async_url = response_stop.headers.get('Azure-AsyncOperation')
        if async_url:
            while True:
                response_status = requests.get(async_url, headers=headers)
                status = response_status.json().get('status')
                if status == 'Succeeded':
                    logging.info(f'Container app {containerAppName} has successfully stopped.')
                    break
                elif status == 'Failed':
                    logging.error(f'Failed to stop container app: {response_status.text}')
                    break
                time.sleep(10)  # Wait before polling again
        else:
            logging.info('No async operation URL provided. Unable to check stop status.')
            time.sleep(30)
    else:
        logging.error(f'Failed to send stop command to container app: {response_stop.text} and {response_stop.status_code}')

    # After stopping, construct the URL to start the container app
    url_start = f"https://management.azure.com/subscriptions/{subscriptionId}/resourceGroups/{resourceGroupName}/providers/Microsoft.App/containerApps/{containerAppName}/start?api-version=2023-08-01-preview"

    # Make the POST request to start the container app
    response_start = requests.post(url_start, headers=headers)

    # Check the response for the start operation
    if response_start.status_code == 202:
        logging.info(f'Start command sent to container app: {containerAppName}')
    else:
        logging.error(f'Failed to send start command to container app: {response_start.text} and {response_start.status_code}')