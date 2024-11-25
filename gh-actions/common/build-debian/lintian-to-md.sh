#!/usr/bin/env bash
set -eu

input_file=${INPUT_FILE:-/dev/stdin}
output_file=${OUTPUT_FILE:-/dev/stdout}

function add_header() {
  {
    echo "| Result | Pacakge | Tag | Details |"
    echo "|:--:|:--:|--|--|"
  } >> "${output_file}"
}

while IFS="" read -r l; do
  # Split the line in an array of strings so that:
  # 0) The result kind
  # 1) The package name
  # 2) The tag
  # 3) The error details
  mapfile -t parsed_tag < <(echo "$l" \
    | sed -n 's/\s*\([A-Z]\+\): \([^:]*\): \([^ ]\+\)\s*\(.*\)/\1\n\2\n\3\n\4/p')

  if [ "${#parsed_tag[@]}" -eq 0 ]; then
    continue;
  fi

  if [ -z "${header_added:-}" ]; then
    add_header
    header_added=true
  fi

  case "${parsed_tag[0]}" in
    E) echo -n "| 🔴 |" >> "${output_file}";; # Error
    W) echo -n "| 🟠 |" >> "${output_file}";; # Warning
    I) echo -n "| 🟡 |" >> "${output_file}";; # Info
    P) echo -n "| ⚪ |" >> "${output_file}";; # Pedantic
    C) echo -n "| ⚪ |" >> "${output_file}";; # Classification
    O) echo -n "| 🔵 |" >> "${output_file}";; # Override
    *) echo -n "| ❓ |" >> "${output_file}";; # Unknown
  esac

  {
    echo -n '`'"${parsed_tag[1]}"'` |'
    echo -n '`'"${parsed_tag[2]}"'` |'
    echo "${parsed_tag[3]} |"
  } >> "${output_file}"
done < "${input_file}"
