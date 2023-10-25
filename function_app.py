import azure.functions as func
import logging
import requests
from datetime import datetime
import json#bourne

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

# make this configurable via a env variable ..
domain = "https://plus-test.ssc-spc.gc.ca/"

@app.route(route="http_trigger")
def http_trigger(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')

    # TODO: remove this later this is just a quick sanity check
    response = requests.get("https://google.com")
    if response.status_code == 200:
        logging.info("Able to reach google.com..")

    ids = _get_all_ids()

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

    response = requests.get(domain + "/en/rest/all-ids")
    json_data = response.json()  
    # save the data to a file  
    with open('preload/ids-{}.json'.format(date), 'w') as f:  
        json.dump(json_data, f) 

    logging.info("Getting all ids that need to be processed...")
    # TODO: do an actual call here..
    f = open("preload/ids-{}.json".format(date))
    data = json.load(f)
    for d in data:
        ids.append((d["nid"], d["type"]))

    return ids