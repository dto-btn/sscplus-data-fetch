import json  # bourne
import logging
import os
from datetime import datetime

import azure.durable_functions as df
import azure.functions as func
from dotenv import load_dotenv
import openai
import requests
from azure.storage.blob import BlobServiceClient
from langchain.chat_models import AzureChatOpenAI
from langchain.embeddings import OpenAIEmbeddings
from llama_index import (Document, LangchainEmbedding, LLMPredictor, ServiceContext,
                         VectorStoreIndex,
                         set_global_service_context)
from llama_index.callbacks import CallbackManager, LlamaDebugHandler
from tenacity import retry, stop_after_attempt, wait_fixed
import glob

load_dotenv()

app = df.DFApp(http_auth_level=func.AuthLevel.FUNCTION)

connection_string   = os.getenv("StorageConnectionString")
blob_service_client = BlobServiceClient.from_connection_string(str(connection_string))

openai_endpoint_name    = os.getenv("AzureOpenAIEndpoint")
azure_openai_key        = os.getenv("AzureOpenAIKey")

openai.api_type    = os.environ["OPENAI_API_TYPE"]    = 'azure'
openai.api_base    = os.environ["OPENAI_API_BASE"]    = f"https://{openai_endpoint_name}.openai.azure.com/"
openai.api_version = os.environ["OPENAI_API_VERSION"] = "2023-07-01-preview"
openai.api_key     = os.environ["OPENAI_API_KEY"]     = azure_openai_key # type: ignore

# make this configurable via a env variable ..
domain = "https://plus-test.ssc-spc.gc.ca"

@app.route(route="fetchdata")
@app.durable_client_input(client_name="client")
async def fetch_data(req: func.HttpRequest, client) -> func.HttpResponse:
    '''
    this durable client will fire the orchestrator to get all the ids
    necessary to do a data fetch from ssc plus drupal api
    and will store all the json payload in a azure blob storage
    '''
    logging.debug('triggered!!!')

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

@app.route(route="buildindex")
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
    pages = []

    logging.info("getting pages ...")

    container_client = blob_service_client.get_container_client("sscplusdata")
    blobs = container_client.list_blobs("preload/" + date + "/")

    for blob in blobs:
        blob_client = container_client.get_blob_client(blob)
        # Download the blob data and decode it to string
        data = blob_client.download_blob().readall().decode('utf-8')
        if data is not None:
            page = json.loads(data)
            if isinstance(page, list) and page:
                page = page[0] # sometimes the object is boxed into an array, not useful to us
            if isinstance(page, dict):
                page["filename"] = blob_client.blob_name
                pages.append(page)

    return pages

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
                'date': page["date"]
            }
        )
        documents.append(document)
        logging.info(document.metadata['filename'])

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

def _get_service_context(model: str, context_window: int, temperature: float = 0.7, num_output: int = 800) -> "ServiceContext":
    chunk_overlap_ratio = 0.1 # overlap for each token fragment

    # using same dep as model name because of an older bug in langchains lib (now fixed I believe)
    llm = _get_llm(model, temperature)

    llm_predictor = _get_llm_predictor(llm)

    # limit is chunk size 1 atm
    embedding_llm = LangchainEmbedding(
        OpenAIEmbeddings(
            model="text-embedding-ada-002", 
            deployment="text-embedding-ada-002", 
            openai_api_key=openai.api_key,
            openai_api_base=openai.api_base,
            openai_api_type=openai.api_type,
            openai_api_version=openai.api_version),
            embed_batch_size=1)
    
    llama_debug = LlamaDebugHandler(print_trace_on_end=True)
    callback_manager = CallbackManager([llama_debug])

    return ServiceContext.from_defaults(llm_predictor=llm_predictor, embed_model=embedding_llm, callback_manager=callback_manager, chunk_size=2048)

def _get_llm(model: str, temperature: float = 0.7):
    return AzureChatOpenAI(model=model, 
                           deployment_name=model,
                           temperature=temperature,)

def _get_llm_predictor(llm) -> LLMPredictor:
    return LLMPredictor(llm=llm,)