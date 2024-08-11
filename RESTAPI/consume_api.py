import requests
import json

response = requests.get('http://api.stackexchange.com/2.3/questions?order=desc&sort=activity&site=stackoverflow')

print(response.json())

for question in response.json()['items']:
    print(question['title'])
    print(question['link'])
    print("\n")