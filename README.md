# sscplus-data-fetch
app that will fetch data from the drupal rest api (from ssc plus) and feed them out to a storage device

## infrastructure

Checkout the [infrastructure project](https://github.com/dto-btn/infrastructure) then run the following commands:

```bash
cd live/sandbox/ssplus-data-fetch
terragrunt plan --terragrunt-source ~/git/sscplus-data-fetch/terraform
```

Etc ...

## dev setup

This is how dev should setup to run this project on their work computers

### virtual env

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt --upgrade
```

Might need to run `Ctrl+Shift+P` in VSCode, type `Python: Create environment...` and follow instructions if needed.


## documentation

* [function app in VSCode](https://learn.microsoft.com/en-ca/azure/azure-functions/functions-develop-vs-code?tabs=node-v3%2Cpython-v2%2Cisolated-process&pivots=programming-language-python)