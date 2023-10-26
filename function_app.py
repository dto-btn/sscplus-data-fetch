import azure.functions as func
import logging
import requests
from datetime import datetime
import json#bourne
from azure.storage.blob import BlobServiceClient, BlobClient, ContainerClient
import os

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

connection_string = str(os.getenv("StorageConnectionString"))

# make this configurable via a env variable ..
domain = "https://plus-test.ssc-spc.gc.ca"

@app.route(route="http_trigger")
def http_trigger(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')

    # TODO: remove this later this is just a quick sanity check
    response = requests.get("https://ipinfo.io/ip")
    if response.status_code == 200:
        logging.info(f"Able to reach ipinfo.io/ip... External ip is: {response.text}")

    # loads all the ids that need to be processed
    ids = _get_all_ids()
    # for each of the ids load the json content for them and then split the content into appropriate folder (en/fr)
    _download_pages(ids)


    if ids:
        return func.HttpResponse(f"Successfully pulled {len(ids)} ids from the API and saved them to disk.")
    else:
        return func.HttpResponse(
             "Unable to read from SSCPlus Druap API...",
             status_code=500
        )

def _get_all_ids():
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

    ids = []
    date = datetime.now().strftime("%Y-%m-%d")

    try:
        r = _get_and_save(domain + "/en/rest/all-ids", "ids-{}.json".format(date))
    except Exception as e:
        logging.error("Unable to send request and/or parse json. Error:" + str(e))
        return []

    logging.info("Getting all ids that need to be processed...")
    for d in r:
        ids.append((d["nid"], d["type"]))

    return ids

def _download_pages(ids):
    """
    Will query the https://plus-test.ssc-spc.gc.ca/en/rest/page-by-id/336 API
    we make two separate calls, 1 for en and 1 for fr content.
    """
    try:
        for id in ids:
            logging.debug(f"Processing file id {id}")
            # save page in preload/<type>/en/<id>.json
            _get_and_save(domain + "/en/rest/page-by-id/" + str(id[0]), f"preload/{id[1]}/en/{str(id[0])}.json")
            # save page in preload/<type>/fr/<id>.json
            _get_and_save(domain + "/fr/rest/page-by-id/" + str(id[0]), f"preload/{id[1]}/fr/{str(id[0])}.json")
    except Exception as e:
        logging.error("Unable to download separate page file. Error:" + str(e))

def _get_and_save(url, blob_name):
    response = requests.get(url, verify=False)
    blob_service_client = BlobServiceClient.from_connection_string(connection_string)
    blob_client = blob_service_client.get_blob_client("sscplusdata", blob_name)
    blob_client.upload_blob(json.dumps(response.json()).encode('utf-8'), overwrite=True)

    return response.json()
