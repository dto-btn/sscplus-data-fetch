import azure.functions as func
import azure.durable_functions as df
import logging
import requests
from datetime import datetime
import json#bourne
from azure.storage.blob import BlobServiceClient, BlobClient, ContainerClient
import os

from tenacity import retry, stop_after_attempt, wait_fixed

app = df.DFApp(http_auth_level=func.AuthLevel.FUNCTION)

connection_string = str(os.getenv("StorageConnectionString"))

# make this configurable via a env variable ..
domain = "https://plus-test.ssc-spc.gc.ca"

@app.route(route="orchestrator")
@app.durable_client_input(client_name="client")
async def http_trigger(req: func.HttpRequest, client) -> func.HttpResponse:
    logging.info('triggered!!!')

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
    cutoffdate = datetime.now().strftime("%Y-%m-%d")
    ids = yield context.call_activity("get_all_ids", cutoffdate)
    download_pages_tasks = [ context.call_activity("download_page", page) for page in ids ]
    list_of_paths = yield context.task_all(download_pages_tasks)
    if not download_pages_tasks:
        logging.error("download_pages_tasks is empty or None")
        return
    # Flatten the list of paths
    paths = [path for sublist in list_of_paths for path in sublist]
    return paths

# Activity
@app.activity_trigger(input_name="cutoffdate")
def get_all_ids(cutoffdate: str) -> list[tuple[str, str]]:
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
    logging.info(f'cutoff date is {cutoffdate}')
    ids = []
    date = datetime.now().strftime("%Y-%m-%d")

    try:
        r = _get_and_save(f"{domain}/en/rest/all-ids", f"ids-{date}.json")
        logging.info("Getting all ids that need to be processed...")
        for d in r:
            ids.append((d["nid"], d["type"]))
    except Exception as e:
        logging.error("Unable to send request and/or parse json. Error:" + str(e))
        return []

    return ids

# Activity
@app.activity_trigger(input_name="page")
def download_page(page):
    """
    Will query the https://plus-test.ssc-spc.gc.ca/en/rest/page-by-id/336 API
    we make two separate calls, 1 for en and 1 for fr content.
    """
    paths = []
    try:
        nid = page[0]
        type = page[1]
        logging.debug(f"Processing file id {nid}")
        _get_and_save(f"{domain}/en/rest/page-by-id/{nid}", f"preload/{type}/en/{nid}.json")
        _get_and_save(f"{domain}/fr/rest/page-by-id/{nid}", f"preload/{type}/fr/{nid}.json")
        paths.append(f"preload/{type}/en/{nid}.json")
        paths.append(f"preload/{type}/fr/{nid}.json")
    except Exception as e:
        logging.error("Unable to download separate page file. Error:" + str(e))

    return paths

@retry(stop=stop_after_attempt(3), wait=wait_fixed(1)) 
def _get_and_save(url, blob_name):
    response = requests.get(url, verify=False)
    blob_service_client = BlobServiceClient.from_connection_string(connection_string)
    blob_client = blob_service_client.get_blob_client("sscplusdata", blob_name)
    blob_client.upload_blob(json.dumps(response.json()).encode('utf-8'), overwrite=True)

    return response.json()
