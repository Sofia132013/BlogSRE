#!/usr/bin/env python3
"""Delete only users recorded by one traffic run, with their own demo content."""
import json
import re
import subprocess
import sys
from pathlib import Path

path = Path(sys.argv[1] if len(sys.argv) > 1 else "artifacts/slo-demo-users.json")
manifest = json.loads(path.read_text())
run, users = manifest["run"], manifest["users"]
if not re.fullmatch(r"slodemo_[0-9a-f]{12}", run) or not users or any(
    not re.fullmatch(re.escape(run) + r"_[0-9a-f]{8}", name) for name in users
):
    raise SystemExit("Invalid manifest; no data deleted")
program = '''
import json, sys
from django.contrib.auth import get_user_model
users = json.loads(sys.stdin.read())
query = get_user_model().objects.filter(username__in=users, is_staff=False, is_superuser=False)
print(query.delete())
'''
subprocess.run(["kubectl", "--context=blog-sre", "-n", "blog-sre", "exec", "-i", "deployment/blog-web", "-c", "web", "--",
                "python", "manage.py", "shell", "-c", program], input=json.dumps(users), text=True, check=True)
path.unlink()
print("Demo accounts removed; existing users were excluded.")
