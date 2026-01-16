#!/usr/bin/env bash

source .venv/bin/activate

export PYTHONPATH="${PYTHONPATH}:${PWD}/custom_components"

hass --config "${PWD}/config" --debug

# list users
#hass --script auth --config "${PWD}/config" list

# change user password
#hass --script auth --config "${PWD}/config" change_password existing_user new_password

# user: thomas
# http://localhost:8123/
