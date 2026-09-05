#!/bin/sh
set -eu

image_name="${1:-asfbot:verify}"
docker build -t "$image_name" .

runtime_user="$(docker image inspect "$image_name" --format '{{.Config.User}}')"
if [ -z "$runtime_user" ] || [ "$runtime_user" = "root" ] || [ "$runtime_user" = "0" ]; then
    echo "container must configure a non-root runtime user" >&2
    exit 1
fi

healthcheck="$(docker image inspect "$image_name" --format '{{json .Config.Healthcheck}}')"
if [ -z "$healthcheck" ] || [ "$healthcheck" = "null" ]; then
    echo "container must configure a healthcheck" >&2
    exit 1
fi

printf 'verified image=%s user=%s healthcheck=configured\n' "$image_name" "$runtime_user"
