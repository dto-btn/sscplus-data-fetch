import azure.functions as func
import azure.durable_functions as df
import logging
import requests
from datetime import datetime
import json#bourne
from azure.storage.blob import BlobServiceClient
import os

from tenacity import retry, stop_after_attempt, wait_fixed

app = df.DFApp(http_auth_level=func.AuthLevel.FUNCTION)

connection_string = str(os.getenv("StorageConnectionString"))
blob_service_client = BlobServiceClient.from_connection_string(connection_string)

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
            pages.append({"id": d["nid"], "type": d["type"], "url": f"{domain}/en/rest/page-by-id/{d['nid']}", "blob_name": f"preload/{dates[0]}/{type}/en/{d['nid']}.json"})
            pages.append({"id": d["nid"], "type": d["type"], "url": f"{domain}/fr/rest/page-by-id/{d['nid']}", "blob_name": f"preload/{dates[0]}/{type}/fr/{d['nid']}.json"})
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
