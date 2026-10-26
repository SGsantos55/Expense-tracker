# How Spendly is Deployed: CI/CD Explained (Beginner Friendly)

This document explains, step by step, how the Spendly Flask app gets from
your computer to a live website on the internet — and how it automatically
re-deploys every time you push code. It is written for someone new to
deployment, so every term is explained.

---

## 1. First, what do these words mean?

- **CI (Continuous Integration):** Every time code changes, it is
  automatically built and tested so mistakes are caught early.
- **CD (Continuous Deployment/Delivery):** Every time code changes (and
  passes checks), it is automatically released to a live server.
- **Pipeline:** The automated sequence of steps (build → test → deploy)
  that runs for you instead of you doing it by hand.
- **Render:** The cloud hosting platform we deploy to (https://render.com).
  It runs our Flask app and our PostgreSQL database.
- **GitHub Actions:** GitHub's built-in automation system. It can run your
  own scripts (like tests) automatically when you push code.

> **Important honesty note:** This project does **NOT** currently use a
> GitHub Actions workflow file. Our automatic deployments are handled by
> **Render's own built-in auto-deploy feature**, which connects directly to
> GitHub. Section 5 explains how you could *add* GitHub Actions on top if you
> want automated testing before deploys.

---

## 2. The big picture (what actually happens today)

```
 You write code
       │
       │  git push origin main
       ▼
┌──────────────┐     webhook      ┌───────────────────────────┐
│    GitHub    │ ───────────────▶ │           Render          │
│ (your repo)  │  "new commit!"   │  1. Pulls your code       │
└──────────────┘                  │  2. Builds it (install)   │
                                  │  3. Starts it (gunicorn)  │
                                  │  4. Health-checks "/"     │
                                  │  5. Switches traffic live │
                                  └───────────────────────────┘
                                              │
                                              ▼
                                  https://spendly-yswa.onrender.com
```

**In plain English:** You push to the `main` branch on GitHub. Render is
"watching" that branch. The moment it sees a new commit, it automatically
rebuilds and redeploys the app. You do nothing else. That is the "CD"
(Continuous Deployment) part.

---

## 3. The configuration that makes this work

### 3a. `render.yaml` (Infrastructure as Code)

Instead of clicking buttons in a dashboard, our infrastructure is described
in a file called `render.yaml`. "Infrastructure as Code" means the servers
and database are defined in a text file you can version-control.

```yaml
services:
  - type: web                 # a public website/API
    name: spendly
    runtime: python           # it's a Python app
    plan: free                # free tier
    region: oregon            # data center location
    branch: main              # deploy from the "main" branch
    autoDeployTrigger: commit # 👈 THIS enables auto-deploy on every commit
    buildCommand: pip install -r requirements.txt   # how to BUILD
    startCommand: gunicorn app:app --bind 0.0.0.0:$PORT  # how to RUN
    healthCheckPath: /        # Render pings "/" to confirm it's alive
    envVars:
      - key: PYTHON_VERSION
        value: "3.12.7"
      - key: SECRET_KEY
        generateValue: true   # Render invents a secure random secret
      - key: DATABASE_URL
        fromDatabase:         # automatically wired to our database below
          name: spendly-db
          property: connectionString

databases:
  - name: spendly-db
    databaseName: spendly
    plan: free
    region: oregon
    ipAllowList: []           # no outside network access (internal only)
```

**Line-by-line meaning of the important parts:**

| Setting | What it does |
|--------|--------------|
| `autoDeployTrigger: commit` | Tells Render to redeploy on every push — this is the heart of CD. |
| `buildCommand` | The "build" step: installs Python libraries from `requirements.txt`. |
| `startCommand` | The "run" step: starts the app with **gunicorn**, a production web server. |
| `$PORT` | Render tells the app which port to listen on via this variable. You must bind to it. |
| `healthCheckPath: /` | Render keeps checking this URL. If it returns HTTP 200, the deploy is "healthy" and goes live. |
| `SECRET_KEY generateValue: true` | Render auto-generates a strong secret so we never hard-code one. |
| `DATABASE_URL fromDatabase` | Render automatically injects the database connection string — no copy-pasting passwords. |

### 3b. `requirements.txt`

Lists the Python packages the app needs. During the **build** step Render
runs `pip install -r requirements.txt`. The key production package here is
`gunicorn` (the server that actually serves the app to the public).

### 3c. The database tables create themselves

In `app.py`, this runs when the app starts up:

```python
with app.app_context():
    init_db()   # creates tables if they don't exist
    seed_db()   # adds sample data the first time
```

So on the very first deploy, the empty PostgreSQL database automatically
gets its tables and a demo user. No manual "migration" command needed.

---

## 4. The deploy lifecycle, step by step

When you run `git push origin main`, here is exactly what Render does:

1. **Trigger:** GitHub notifies Render (via a webhook) that `main` changed.
2. **Clone:** Render downloads the latest code.
3. **Build:** Runs `pip install -r requirements.txt`.
4. **Start:** Runs `gunicorn app:app --bind 0.0.0.0:$PORT`. On startup the
   app creates/seeds the database tables.
5. **Health check:** Render repeatedly requests `/`. When it returns
   `HTTP 200`, the new version is considered healthy.
6. **Go live (zero-downtime):** Render switches public traffic from the old
   version to the new one. If the health check *fails*, the old version
   keeps running so the site never goes down.

The live site is: **https://spendly-yswa.onrender.com**

> **Free-tier note:** On the free plan the service "sleeps" after inactivity,
> so the first visit after idle time can take ~30–60 seconds to wake up.

---

## 5. (Optional) Adding GitHub Actions for CI (automated testing)

Right now Render deploys code the moment you push — it does **not** run our
`pytest` tests first. A common improvement is to add **GitHub Actions** so
your tests run on every push/pull request. If tests fail, you find out
immediately.

You would create a file at `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [ main ]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: spendly_test
        ports: [ "5432:5432" ]
        options: >-
          --health-cmd pg_isready --health-interval 10s
          --health-timeout 5s --health-retries 5
    steps:
      - uses: actions/checkout@v4            # download the code
      - uses: actions/setup-python@v5        # install Python
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt # install dependencies
      - run: pytest                          # run the tests
        env:
          DATABASE_URL: postgresql://postgres:postgres@localhost:5432/spendly_test
```

**How this would work together with Render:**

- **GitHub Actions** = the **CI** half → runs tests automatically.
- **Render auto-deploy** = the **CD** half → ships the app automatically.

For stricter safety you can configure Render to deploy only *after* the
GitHub Actions checks pass (branch protection rules), so broken code never
reaches production.

---

## 6. Quick FAQ

**Q: Where is the "pipeline" defined?**
A: The deploy pipeline lives in `render.yaml` + Render's auto-deploy setting.
There is no GitHub Actions pipeline yet (see Section 5 to add one).

**Q: How do I deploy a change?**
A: Just `git add`, `git commit`, and `git push origin main`. That's it —
Render handles the rest.

**Q: How do I see deploy logs?**
A: In the Render Dashboard for the `spendly` service, open the "Logs" and
"Events" tabs.

**Q: What if a deploy breaks the site?**
A: Render keeps the previous healthy version running until the new one
passes its health check, and you can one-click "Rollback" to an earlier
deploy in the Dashboard.
