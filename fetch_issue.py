import urllib.request
import json

url = 'https://api.github.com/repos/chatwoot/chatwoot/issues/13556/comments'
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
try:
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode())
        with open('github_comments.txt', 'w', encoding='utf-8') as f:
            for c in data:
                f.write(f"--- Comment by {c['user']['login']} ---\n")
                f.write(str(c.get('body', '')) + '\n\n')
except Exception as e:
    with open('github_comments.txt', 'w', encoding='utf-8') as f:
        f.write('Error: ' + str(e))
