# shellcheck shell=bash

set -o errexit
set -o nounset
set -o pipefail

helper_dir="$(cd -- "$(/usr/bin/dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
share_dir="$(cd -- "${helper_dir}/../../share" && pwd -P)"
readonly helper_dir share_dir

export PYTHONPATH="${share_dir}${PYTHONPATH:+:${PYTHONPATH}}"

gitrepo_exec_python_module() {
	local -r module=$1
	shift
	exec /usr/bin/python3 -m "$module" "$@"
}
