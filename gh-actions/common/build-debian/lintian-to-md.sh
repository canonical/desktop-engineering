#!/usr/bin/env bash
set -eu

input_file=${INPUT_FILE:-/dev/stdin}
output_file=${OUTPUT_FILE:-/dev/stdout}

# We can't use fully markdown output because the details usage breaks it.

function add_header() {
  {
    echo "<table align='center'>"
    echo "  <tr>"
    echo "    <th>Result</th>"
    echo "    <th>Package</th>"
    echo "    <th>Tag</th>"
    echo "    <th>Details</th>"
    echo "  </tr>"
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

  echo "  <tr>" >> "${output_file}"

  case "${parsed_tag[0]}" in
    E) echo "    <td>🔴</td>" >> "${output_file}";; # Error
    W) echo "    <td>🟠</td>" >> "${output_file}";; # Warning
    I) echo "    <td>🟡</td>" >> "${output_file}";; # Info
    P) echo "    <td>⚪</td>" >> "${output_file}";; # Pedantic
    C) echo "    <td>⚪</td>" >> "${output_file}";; # Classification
    O) echo "    <td>🔵</td>" >> "${output_file}";; # Override
    *) echo "    <td>❓</td>" >> "${output_file}";; # Unknown
  esac

  tag_details=$(lintian-explain-tags --output-width 80 "${parsed_tag[2]}" | \
    grep -vF "${parsed_tag[0]}: ${parsed_tag[2]}" | \
    sed "s,^[A-Z]:[ ]*,,g" | \
    uniq)
  {
    echo "    <td><code>${parsed_tag[1]}</code></td>"
    echo "    <td><details><summary><code>${parsed_tag[2]}</code></summary>"
    echo -e "\n"'```'"\n${tag_details}\n"'```'"\n</details>"
    echo "    </td>"
    echo "    <td>${parsed_tag[3]}</td>"
    echo "  </tr>"
  } >> "${output_file}"
done < "${input_file}"

if [ -n "${header_added:-}" ]; then
  echo "</table>" >> "${output_file}"
fi
