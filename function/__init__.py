from azure.core.pipeline import Pipeline
from azure.core.pipeline.transport import HttpRequest, HttpResponse
from azure.core.pipeline.policies import BearerTokenCredentialPolicy, HttpLoggingPolicy, RedirectPolicy  
from azure.core.pipeline.transport import RequestsTransport
from azure.identity import DefaultAzureCredential, InteractiveBrowserCredential
import logging
from dotenv import load_dotenv
from msal import ConfidentialClientApplication, PublicClientApplication
import os
import json
from bs4 import BeautifulSoup
from pathlib import Path

load_dotenv()

logging.basicConfig(level=logging.DEBUG)
logging.getLogger("msal").setLevel(logging.WARN)

DefaultAzureCredential()

def _msal_login():
    app = PublicClientApplication(
        os.getenv("CLIENT_ID"),
        authority="https://login.microsoftonline.com/d05bc194-94bf-4ad6-ae2e-1db0f2e38f5e")

    result = None

    accounts = app.get_accounts()
    if accounts:
        # If so, you could then somehow display these accounts and let end user choose
        print("Pick the account you want to use to proceed:")
        for a in accounts:
            print(a["username"])
        # Assuming the end user chose this one
        chosen = accounts[0]
        # Now let's try to find a token in cache for this account
        result = app.acquire_token_silent(["User.Read"], account=chosen)

    if not result:
        # So no suitable token exists in cache. Let's get a new one from Azure AD.
        # result = app.acquire_token_interactive(["User.Read"], login_hint=os.getenv("USERNAME"))
        result = app.acquire_token_by_authorization_code(..., scopes=["https://graph.microsoft.com/.default"])
    if "access_token" in result:
        print(result["access_token"])  # Yay!
    else:
        print(result.get("error"))
        print(result.get("error_description"))
        print(result.get("correlation_id"))  # You may need this when reporting a bug
    # credential = DefaultAzureCredential()
    # credential_policy = BearerTokenCredentialPolicy(credential, 'https://graph.microsoft.com/.default')

    # policies = [
    #     UserAgentPolicy("SSCPlusDrupal"),  
    #     NetworkTraceLoggingPolicy(), 
    #     credential_policy,
    #     HttpLoggingPolicy(),
    #     RedirectPolicy()
    # ]

    # transport = RequestsTransport(connection_verify=False)
    # pipeline = Pipeline(transport=transport, policies=policies) 
    # request = HttpRequest('GET', 'https://plus-test.ssc-spc.gc.ca/en/rest/all-ids')
    # response = pipeline.run(request)

    # # Get the response  
    # print("RESPONSE HTTP CODE: " + str(response.http_response.status_code)) 
    # print("RESPONSE BODY: " + str(response.http_response.headers))
    # print(response.http_response.text())

def _get_all_ids():
    """
    todo: get all ids from the https://plus-test.ssc-spc.gc.ca/en/rest/all-ids call
    
    refine process so we can be more selective about the ids we retreive... 
    produce a list that we will be looking at, specifically re-indexing a specific portion.
    •	/rest/updated-ids/week
      o	same
      o	updated with past 7 days
    •	/rest/updated-ids/month
      o	same
      o	updated within last 30 days
    """
    print("Getting all ids that need to be processed...")
    
    # for test purposes right now the file is stored in data/ids-2023-10-17.json
    # todo: load file ... and content into an array..
    return [(336, "article"), (534, "gigabit"), (703, "structured_page")]

def _download_pages(ids):
    """
    Will query the https://plus-test.ssc-spc.gc.ca/en/rest/page-by-id/336 API
    and get a json response of the page that has both en and fr in it.
    """
    for id in ids:
        print("Loading in https://plus-test.ssc-spc.gc.ca/en/rest/page-by-id/" + str(id[0]) + " type ==> " + id[1])
        # save page in preload/<type>/<id>.json

def _split_pages(ids):
    """
    for the purpose of this exercise there is so few pages that we can load all of them into memory
    we also have to split them into two separate page, each id gives us english and french and for 
    the purpose of metadata and searching its better if they are split in the index
    """
    #make sure directories exists..
    Path("data/en").mkdir(parents=True, exist_ok=True)
    Path("data/fr").mkdir(parents=True, exist_ok=True)

    for id in ids:
        print("Splitting https://plus-test.ssc-spc.gc.ca/en/rest/page-by-id/" + str(id[0]) + " type ==> " + id[1])
        f = open(''.join(["preload/", str(id[1]), "/", str(id[0]), ".json"]))
        data = json.load(f)
        for d in data:
            soup = BeautifulSoup(d["body"], "html.parser", from_encoding="UTF-8")
            content = {
                "title": d["title"],
                "url": d["url"],
                "text": ' '.join(soup.stripped_strings),
                "date": d["date"] # TODO: date seems to be inconcistent field.
            }

            with open("data/{}/{}.json".format(d["langcode"], d["nid"]), 'w') as f:
                f.write(json.dumps(content, indent=4))

# loads all the ids that need to be processed
ids = _get_all_ids()
# for each of the ids load the json content for them and store them in appropriate folder, then split the content
_download_pages(ids)
_split_pages(ids)

# at this point the data/ folder is ready to be read and processed.