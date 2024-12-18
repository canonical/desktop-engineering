#!/usr/bin/env bash

# Configure here all the directories where are source files
SOURCE_FILES="src/*.[ch] tests/*.[ch]"

if [[ "$1" == "pre-commit" ]]; then
    echo Checking source style
    PRE_COMMIT=1
else
    PRE_COMMIT=0
fi

passed=true
for file in $SOURCE_FILES; do
    if [ $# -eq 0 ]; then
        # no parameters? Just apply the changes
        echo Formating "$file"
        clang-format -i "$file"
    else
        # any parameter? check that the formatting is fine
        clang-format "$file" > "$file.formatted"
        echo Checking $file
        if [ $PRE_COMMIT -eq 0 ]; then
            if ! diff "$file" "$file.formatted"; then
                passed=false
            fi
        else
            if ! diff "$file" "$file.formatted" > /dev/null; then
                passed=false
            fi
        fi
        rm "$file.formatted"
    fi
done
if [ $passed = false ]; then
    echo Failed to pass clang-format check
    exit 1
fi
