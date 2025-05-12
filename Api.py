import requests

url = "https://courses.altacademy.org/admin/api/v2/users/walid.ahmed@altacademy.org"

querystring = {"include_suspended":"true"}

headers = {
    "Authorization": "Bearer HHvkFXClmYF49GV4dInM1OVHMGnnGqdqhaI5Msal",
    "Lw-Client": "645a0bc1ebb978f660035e95",
    "Accept": "application/json"
}

response = requests.get(url, headers=headers, params=querystring)

print(response.json())