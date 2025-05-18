TOKEN=$(curl -s -X POST http://localhost:8000/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=secret" | grep -o '"access_token":"[^"]*' | cut -d':' -f2 | tr -d '"')

wrk -t10 -c10 -d30s -H "Authorization: Bearer $TOKEN" http://localhost:8000/users/admin

wrk -t10 -c10 -d30s -H "Authorization: Bearer $TOKEN" http://localhost:8000/nocache/users/admin