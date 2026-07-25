#!/bin/bash
echo "--- Path 1 ---"
curl -s -X POST http://localhost:8000/api/v1/ask \
  -H "Content-Type: application/json" \
  -d '{"query": "hello there"}'
echo -e "\n"

echo "--- Path 2 ---"
curl -s -X POST http://localhost:8000/api/v1/ask \
  -H "Content-Type: application/json" \
  -d '{"query": "Is FAKE-DRUG-99 in stock?"}'
echo -e "\n"

echo "--- Path 3 ---"
curl -s -X POST http://localhost:8000/api/v1/ask \
  -H "Content-Type: application/json" \
  -d '{"query": "Is PAN-40 in stock?"}'
echo -e "\n"

echo "--- Path 4 ---"
curl -s -X POST http://localhost:8000/api/v1/ask \
  -H "Content-Type: application/json" \
  -d '{"query": "What is a substitute for PAN-40?"}'
echo -e "\n"

echo "--- Path 5 ---"
curl -s -X POST http://localhost:8000/api/v1/ask \
  -H "Content-Type: application/json" \
  -d '{"query": "Is PAN-40 safe during pregnancy?"}'
echo -e "\n"
