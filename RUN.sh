#!/bin/bash
bash -c 'source venv/bin/activate; echo "Timed controller:"; python junction_timed.py 24 60; echo "Fuzzy controller:"; python junction_fuzzy.py 24 60;'