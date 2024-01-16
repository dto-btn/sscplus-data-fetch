# sscplus-data-fetch
app that will fetch data from the drupal rest api (from ssc plus) and feed them out to a storage device

## infrastructure

Checkout the [infrastructure project](https://github.com/dto-btn/infrastructure) then run the following commands:

```bash
cd live/sandbox/ssplus-data-fetch
terragrunt plan --terragrunt-source ~/git/sscplus-data-fetch/terraform
```

If requested for `package.zip` localtion simply create one first and then provide directory path (`zip package.zip function_app.py requirements.txt host.json`)

## dev setup

This is how dev should setup to run this project on their work computers 

### virtual env

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt --upgrade
```

Might need to run `Ctrl+Shift+P` in VSCode, type `Python: Create environment...` and follow instructions if needed.

### running the app

Make sure you install the Azure plugins ([install the Azure Functions extension for Visual Studio Code](https://go.microsoft.com/fwlink/?linkid=2016800))

Then press `F5`.

Run with `python function/__init__.py` (old).

### troubleshooting

I had an issue where the trigger wasn't detected in the V2 model. I had to modify my `local.settings.json` to include this property ([see documentation about it](https://learn.microsoft.com/en-us/azure/azure-functions/create-first-function-vs-code-python?pivots=python-mode-decorators#update-app-settings)): 

```json
{
  "IsEncrypted": false,
  "Values": {
    "AzureWebJobsFeatureFlags": "EnableWorkerIndexing",
    ...
  }
}
```

## documentation

* [function app in VSCode](https://learn.microsoft.com/en-ca/azure/azure-functions/functions-develop-vs-code?tabs=node-v3%2Cpython-v2%2Cisolated-process&pivots=programming-language-python)
* [config client apps to access your services](https://learn.microsoft.com/en-us/azure/app-service/configure-authentication-provider-aad?tabs=workforce-tenant#configure-client-apps-to-access-your-app-service)
* [Confidential client flow](https://github.com/AzureAD/microsoft-authentication-library-for-python/blob/dev/sample/confidential_client_secret_sample.py)
* [condfidential client secret generation](https://github.com/AzureAD/microsoft-authentication-library-for-python/wiki/Client-Credentials#registering-client-secrets-using-the-application-registration-portal)
* [sample python code doing auth with ad](https://learn.microsoft.com/en-us/azure/active-directory/develop/sample-v2-code?tabs=framework#python)