"""Seed realistic SaaS customers: 275 paying users (~$6,147 MRR) + 600 free.
Real company domains (one per paid account), multiple tiers, 10-month growth curve."""
import random
from datetime import datetime, timezone, timedelta
from app import create_app
from app.extensions import db
from app.models import User

app = create_app()
with app.app_context():
    random.seed(7)

    PRICES = {
        "starter_monthly": "price_1TRyLPRvFVBWwnvbFpgeUygM",
        "starter_yearly": "price_1TRyLQRvFVBWwnvbNPXZR0v8",
        "pro_monthly": "price_1TRyLRRvFVBWwnvbqHsy612y",
        "pro_yearly": "price_1TRyLSRvFVBWwnvbeTF30tFz",
    }

    # Real small-SaaS / startup / agency domains — one per paid customer
    COMPANY_DOMAINS = [
        # User-specified real companies
        "pushouse.com", "liinks.co", "speel.co", "postiz.com", "letmeapply.com",
        # Well-known developer/startup tools
        "dub.co", "cal.com", "rows.com", "resend.com", "mailcoach.com",
        "vercel.com", "supabase.com", "railway.app", "render.com", "fly.io",
        "deno.com", "astro.build", "payloadcms.com", "sanity.io", "contentful.com",
        "directus.io", "strapi.io", "pocketbase.com", "clerk.com", "workos.com",
        "stytch.com", "auth0.com", "magic.link", "planetscale.com", "neon.tech",
        "turso.tech", "xata.io", "convex.dev", "upstash.com", "qdrant.tech",
        "pinecone.io", "weaviate.io", "temporal.io", "trigger.dev", "inngest.com",
        "novu.co", "knock.app", "courier.com", "resend.io", "loops.so",
        "beehiiv.com", "convertkit.com", "ghost.org", "typefully.com", "taplio.com",
        "calendly.com", "savvycal.com", "cal.ai", "hubble.cx", "superhuman.com",
        "linear.app", "height.app", "asana.com", "clickup.com", "notion.so",
        "coda.io", "airtable.com", "fibery.io", "todoist.com", "things.app",
        "figma.com", "canva.com", "framer.com", "webflow.com", "readymag.com",
        "spline.design", "rive.app", "lottiefiles.com", "icons8.com", "undraw.co",
        "tinyseed.com", "indie.vc", "earnest.capital", "calmfund.com", "tiny.vc",
        "firstround.com", "ycombinator.com", "sequoia.com", "a16z.com", "foundersfund.com",
        "bessemer.com", "accel.com", "indexventures.com", "greylock.com", "lightspeed.com",
        "shopify.com", "bigcommerce.com", "wix.com", "squarespace.com", "bubble.io",
        "zapier.com", "make.com", "n8n.io", "integromat.com", "automate.io",
        "pipedrive.com", "hubspot.com", "salesforce.com", "close.com", "attio.com",
        "intercom.com", "zendesk.com", "freshdesk.com", "helpjuice.com", "groovehq.com",
        "drift.com", "tawk.to", "crisp.chat", "gorgias.com", "recharge.com",
        "stripe.com", "paddle.com", "lemonsqueezy.com", "gumroad.com", "chargebee.com",
        "recurly.com", "chartmogul.com", "baremetrics.com", "profitwell.com", "paddle.net",
        "segment.com", "amplitude.com", "mixpanel.com", "heap.io", "posthog.com",
        "snowplow.io", "rudderstack.com", "meltano.com", "airbyte.com", "fivetran.com",
        "databricks.com", "snowflake.com", "bigquery.com", "clickhouse.com", "duckdb.org",
        "metabase.com", "looker.com", "tableau.com", "powerbi.com", "superset.com",
        "datadog.com", "newrelic.com", "grafana.com", "sentry.io", "honeycomb.io",
        "lightstep.com", "opsgenie.com", "pagerduty.com", "victorops.com", "squadcast.com",
        "notion.com", "monday.com", "wrike.com", "teamwork.com", "basecamp.com",
        "shortcut.com", "pivotal.com", "jira.com", "trello.com", "gitlab.com",
        "github.com", "bitbucket.com", "gitkraken.com", "sourcetree.com", "tower.com",
        "circleci.com", "jenkins.com", "githubactions.com", "travisci.com", "gitlabci.com",
        "snyk.io", "sonarqube.com", "codeclimate.com", "coveralls.com", "codecov.io",
        "deepsource.io", "semgrep.com", "dependabot.com", "renovatebot.com", "whitesource.com",
        "cloudflare.com", "fastly.com", "akamai.com", "cloudfront.com", "keycdn.com",
        "netlify.com", "amplify.com", "githubpages.com", "surge.sh", "zeit.co",
        "heroku.com", "digitalocean.com", "linode.com", "vultr.com", "ovh.com",
        "scaleway.com", "hetzner.com", "contabo.com", "oraclecloud.com", "azure.com",
        "gcp.com", "ibmcloud.com", "alibabacloud.com", "tencentcloud.com", "baidu.com",
        "mongodb.com", "atlas.com", "couchbase.com", "cassandra.com", "elastic.co",
        "opensearch.com", "algolia.com", "typesense.com", "meilisearch.com", "vespa.ai",
        "redis.com", "memcached.com", "dragonflydb.io", "keydb.io", "aerospike.com",
        "kafka.com", "rabbitmq.com", "nats.io", "pulsar.com", "zeromq.org",
        "grpc.com", "thrift.com", "protobuf.com", "avro.com", "msgpack.com",
        "graphql.com", "apollo.com", "hasura.com", "prisma.com", "dgraph.com",
        "neo4j.com", "arangodb.com", "janusgraph.com", "orientdb.com", "fauna.com",
        "cockroachlabs.com", "tidb.com", "yugabyte.com", "citus.com", "vitess.io",
        "timescale.com", "questdb.io", "influxdb.com", "prometheus.com", "thanos.com",
        "nextcloud.com", "owncloud.com", "seafile.com", "syncthing.com", "dropbox.com",
        "box.com", "gdrive.com", "onedrive.com", "icloud.com", "pcloud.com",
        "mega.io", "tresorit.com", "sync.com", "cryptomator.com", "proton.com",
        "tutanota.com", "mailfence.com", "startmail.com", "fastmail.com", "hey.com",
        "superhuman.io", "sparkmail.com", "canarymail.com", "polymail.com", "newtonmail.com",
        "slack.com", "discord.com", "microsoftteams.com", "zoom.com", "meet.com",
        "whereby.com", "gather.town", "butter.us", "spatial.chat", "remo.co",
        "hopin.com", "bizzabo.com", "whova.com", "swapcard.com", "vFairs.com",
        "eventbrite.com", "meetup.com", "luma.com", "partiful.com", "punchbowl.com",
        "canva.com", "piktochart.com", "venngage.com", "infogram.com", "visme.co",
        "prezi.com", "beautiful.ai", "slidesgo.com", "slideshare.com", "gamma.app",
        "miro.com", "mural.com", "figjam.com", "whimsical.com", "excalidraw.com",
        "lucidchart.com", "draw.io", "gliffy.com", "creately.com", "smartdraw.com",
        "tldraw.com", "diagrams.net", "plantuml.com", "mermaid.com", "graphviz.org",
        "obsidian.com", "roamresearch.com", "logseq.com", "craft.do", "bear.app",
        "notion-ai.com", "mem.ai", "reflection.app", "nvalt.com", "simplenote.com",
        "evernote.com", "onenote.com", "joplinapp.org", "standardnotes.com", "zimwiki.com",
        "todoist.co", "ticktick.com", "anydo.com", "rememberthemilk.com", "habitica.com",
        "forestapp.com", "focusmate.com", "rescuetime.com", "toggl.com", "clockify.com",
        "timely.com", "harvest.com", "hubstaff.com", "timecamp.com", "desktime.com",
        "float.com", "savio.io", "productboard.com", "craft.io", "airfocus.com",
        "prodpad.com", "aha.io", "roadmunk.com", "sharpcloud.com", "productplan.com",
        "usertesting.com", "userinterviews.com", "lookback.com", "maze.co", "optimalworkshop.com",
        "hotjar.com", "fullstory.com", "luckyorange.com", "mouseflow.com", "smartlook.com",
        "crazyegg.com", "optimizely.com", "vwo.com", "googleoptimize.com", "omniconvert.com",
        "unbounce.com", "instapage.com", "leadpages.com", "landerapp.com", "wishpond.com",
        "clickfunnels.com", "kartra.com", "systeme.io", "simvoly.com", "groovefunnels.com",
        "activecampaign.com", "mailchimp.com", "sendinblue.com", "mailerlite.com", "omnisend.com",
        "klaviyo.com", "drip.com", "getresponse.com", "aweber.com", "constantcontact.com",
        "campaignmonitor.com", "customer.io", "braze.com", "iterable.com", "moengage.com",
        "clevertap.com", "onesignal.com", "pusher.com", "ably.com", "pubnub.com",
        "stream.io", "getstream.io", "talkjs.com", "sendbird.com", "cometchat.com",
        "twilio.com", "plivo.com", "vonage.com", "bandwidth.com", "messagebird.com",
        "sinch.com", "infobip.com", "telnyx.com", "46elks.com", "textlocal.com",
        "stripe.net", "adyen.com", "braintree.com", "checkout.com", "mollie.com",
        "worldpay.com", "square.com", "paypal.com", "wise.com", "revolut.com",
        "monzo.com", "n26.com", "chime.com", "brex.com", "ramp.com",
        "mercury.com", "novo.co", "found.com", "lili.co", "bluevine.com",
        "stripecapital.com", "pipe.com", "arc.com", "foundersuite.com", "carta.com",
        "pulley.com", "angelist.com", "equityzen.com", "forge.com", "secfi.com",
        "gusto.com", "justworks.com", "rippling.com", "bamboohr.com", "zenefits.com",
        "deel.com", "remote.com", "oyster.com", "papayaglobal.com", "velocityglobal.com",
        "andela.com", "toptal.com", "upwork.com", "fiverr.com", "freelancer.com",
        "turing.com", "gun.io", "arc.dev", "hired.com", "hackerrank.com",
    ]

    FIRST_NAMES = [
        "James", "Mary", "John", "Patricia", "Robert", "Jennifer", "Michael",
        "Linda", "William", "Elizabeth", "David", "Barbara", "Richard", "Susan",
        "Joseph", "Jessica", "Thomas", "Sarah", "Chris", "Karen", "Daniel",
        "Nancy", "Matthew", "Lisa", "Anthony", "Betty", "Mark", "Sandra",
        "Donald", "Ashley", "Steven", "Kimberly", "Paul", "Emily", "Andrew",
        "Donna", "Joshua", "Michelle", "Kenneth", "Carol", "Kevin", "Amanda",
        "Brian", "Melissa", "George", "Deborah", "Edward", "Stephanie", "Ronald",
        "Rebecca", "Timothy", "Laura", "Jason", "Sharon", "Jeffrey", "Cynthia",
        "Ryan", "Kathleen", "Jacob", "Amy", "Gary", "Shirley", "Nicholas",
        "Angela", "Eric", "Helen", "Jonathan", "Anna", "Stephen", "Brenda",
        "Larry", "Pamela", "Justin", "Nicole", "Scott", "Samantha", "Brandon",
        "Katherine", "Benjamin", "Christine", "Samuel", "Debra", "Gregory",
        "Rachel", "Frank", "Catherine", "Alexander", "Carolyn", "Raymond",
        "Janet", "Patrick", "Ruth", "Jack", "Maria", "Dennis", "Heather",
        "Jerry", "Diane", "Tyler", "Virginia", "Aaron", "Henry", "Sofia",
        "Douglas", "Joyce", "Peter", "Jacqueline", "Zachary", "Chloe", "Adam",
        "Madison", "Nathan", "Grace", "Owen", "Lily", "Connor", "Hannah",
        "Ethan", "Olivia", "Logan", "Zoe", "Caleb", "Natalie", "Mason",
        "Ella", "Lucas", "Riley", "Avery", "Isaac", "Scarlett", "Dylan",
        "Aria", "Carter", "Layla", "Wyatt", "Charlotte", "Levi", "Stella",
        "Julian", "Brianna", "Oscar", "Victoria", "Felix", "Audrey", "Marcus",
        "Claire", "Theo", "Skylar", "Leon", "Aubrey", "Maxwell", "Ellie",
    ]

    LAST_NAMES = [
        "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
        "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
        "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
        "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark",
        "Ramirez", "Lewis", "Robinson", "Walker", "Young", "Allen", "King",
        "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores", "Green",
        "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell",
        "Carter", "Roberts", "Gomez", "Phillips", "Evans", "Turner", "Diaz",
        "Parker", "Cruz", "Edwards", "Collins", "Reyes", "Stewart", "Morris",
        "Morales", "Murphy", "Cook", "Rogers", "Gutierrez", "Ortiz", "Morgan",
        "Cooper", "Peterson", "Bailey", "Reed", "Kelly", "Howard", "Ramos",
        "Kim", "Cox", "Ward", "Richardson", "Watson", "Brooks", "Chavez",
        "Wood", "Bennett", "Gray", "Mendoza", "Ruiz", "Hughes", "Price",
        "Alvarez", "Castillo", "Sanders", "Patel", "Myers", "Long", "Ross",
        "Foster", "Jimenez", "Powell", "Jenkins", "Perry", "Russell",
        "Sullivan", "Bell", "Coleman", "Butler", "Henderson", "Barnes",
        "Fisher", "Vasquez", "Simmons", "Romero", "Jordan", "Patterson",
        "Alexander", "Hamilton", "Graham", "Reynolds", "Griffin", "Wallace",
        "Moreno", "West", "Cole", "Hayes", "Bryant", "Herrera", "Gibson",
        "Ellis", "Tran", "Medina", "Aguilar", "Stevens", "Ford", "Cohen",
        "Acevedo", "Mason", "Duncan", "Boyd", "Meyer", "Palmer", "Welsh",
        "Mills", "Murray", "Berry", "Fowler", "Doyle", "Sherman", "Fleming",
        "Vargas", "Hunter", "Dean", "Holt", "Lamb", "Carlson", "Ferguson",
        "Stone", "Dawson", "Brock", "Bates", "Chapman", "Burns", "Lynch",
    ]

    now = datetime.now(timezone.utc)

    def gen_stripe_id(prefix, length=24):
        chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        return prefix + "_" + "".join(random.choice(chars) for _ in range(length))

    # 10-month growth curve (accelerating: month 1 oldest/smallest)
    MONTH_WEIGHTS = [0.02, 0.03, 0.04, 0.05, 0.07, 0.09, 0.11, 0.14, 0.18, 0.27]

    def growth_date():
        cumulative = 0.0
        month_num = 0
        r = random.random()
        for i, w in enumerate(MONTH_WEIGHTS):
            cumulative += w
            if r <= cumulative:
                month_num = i
                break
        else:
            month_num = len(MONTH_WEIGHTS) - 1
        days_ago_start = (9 - month_num) * 30
        days_ago_end = (8 - month_num) * 30 if month_num < 9 else 0
        if days_ago_start > days_ago_end:
            days_ago = random.randint(days_ago_end, days_ago_start - 1)
        else:
            days_ago = random.randint(0, 29)
        return now - timedelta(days=days_ago, hours=random.randint(0, 23),
                                minutes=random.randint(0, 59))

    # Clear existing non-admin users
    User.query.filter(User.role != "admin").delete()
    db.session.commit()

    used_emails = set()
    used_usernames = set()
    created = 0

    # Pre-compute password hash once
    from werkzeug.security import generate_password_hash
    DEMO_HASH = generate_password_hash("DemoUser!2026")

    # ── PAYING USERS: 275 total → $6,147.50 MRR ────────────────
    # 140 Pro monthly     @ $29      = $4,060.00
    #  50 Starter monthly @ $9       = $450.00
    #  60 Pro yearly      @ $290/yr  = $1,450.00 (amortized)
    #  25 Starter yearly  @ $90/yr   = $187.50 (amortized)
    paying_plans = []
    for _ in range(140):
        paying_plans.append(("pro", PRICES["pro_monthly"], False))
    for _ in range(50):
        paying_plans.append(("starter", PRICES["starter_monthly"], False))
    for _ in range(60):
        paying_plans.append(("pro", PRICES["pro_yearly"], True))
    for _ in range(25):
        paying_plans.append(("starter", PRICES["starter_yearly"], True))

    random.shuffle(paying_plans)

    # Ensure enough unique domains
    domains = list(COMPANY_DOMAINS)
    random.shuffle(domains)
    while len(domains) < len(paying_plans):
        pfx = ["app", "get", "my", "try", "use", "go", "hey", "do", "ok", "hi"]
        base = ["flow", "base", "wise", "hub", "spot", "lab", "kit", "snap", "loop", "stack"]
        suf = [".io", ".co", ".app", ".dev", ".com", ".so", ".gg", ".ai"]
        d = random.choice(pfx) + random.choice(base) + random.choice(suf)
        if d not in domains:
            domains.append(d)

    for i, (plan, price_id, annual) in enumerate(paying_plans):
        fn = random.choice(FIRST_NAMES)
        ln = random.choice(LAST_NAMES)
        domain = domains[i]

        username = f"{fn.lower()}.{ln.lower()}"
        email = f"{fn.lower()}@{domain}"

        while email in used_emails:
            email = f"{fn.lower()}.{ln.lower()}@{domain}"
            if email in used_emails:
                email = f"{fn.lower()}{random.randint(1, 99)}@{domain}"
        while username in used_usernames:
            username = f"{fn.lower()}.{ln.lower()}{random.randint(1, 99)}"
        used_emails.add(email)
        used_usernames.add(username)

        join_date = growth_date()
        period_start = join_date + timedelta(days=random.randint(0, 7))
        uploads_used = random.randint(5, 50) if annual else random.randint(1, 25)

        u = User(
            username=username,
            email=email,
            role="user",
            is_active=True,
            plan=plan,
            plan_period_start=period_start,
            plan_uploads_used=uploads_used,
            plan_is_annual=annual,
            subscription_status="active",
            stripe_customer_id=gen_stripe_id("cus"),
            stripe_subscription_id=gen_stripe_id("sub"),
            stripe_price_id=price_id,
            created_at=join_date,
        )
        u.password_hash = DEMO_HASH
        db.session.add(u)
        created += 1
        if created % 100 == 0:
            db.session.commit()

    db.session.commit()

    # ── FREE USERS: 600 ─────────────────────────────────────────
    FREE_COUNT = 600
    free_domains = ["gmail.com", "yahoo.com", "outlook.com", "hotmail.com",
                    "icloud.com", "proton.me", "fastmail.com", "hey.com",
                    "zoho.com", "aol.com", "gmx.com", "mail.com", "tutanota.com"]

    for i in range(FREE_COUNT):
        fn = random.choice(FIRST_NAMES)
        ln = random.choice(LAST_NAMES)
        d = random.choice(free_domains)
        username = f"{fn.lower()}{ln.lower()}f{i}"
        email = f"{fn.lower()}.{ln.lower()}{i}@{d}"
        while email in used_emails:
            email = f"{fn.lower()}.{ln.lower()}{i}{random.randint(1, 999)}@{d}"
        while username in used_usernames:
            username = f"{fn.lower()}{ln.lower()}f{i}{random.randint(1, 999)}"
        used_emails.add(email)
        used_usernames.add(username)

        join_date = growth_date()
        u = User(
            username=username,
            email=email,
            role="user",
            is_active=True,
            plan="free",
            plan_period_start=join_date,
            plan_uploads_used=random.randint(0, 5),
            plan_is_annual=False,
            subscription_status="active",
            created_at=join_date,
        )
        u.password_hash = DEMO_HASH
        db.session.add(u)
        created += 1
        if created % 200 == 0:
            db.session.commit()

    db.session.commit()

    # ── SUMMARY ─────────────────────────────────────────────────
    total = User.query.count()
    paying = User.query.filter(User.plan != "free").count()
    starters = User.query.filter_by(plan="starter").count()
    pros = User.query.filter_by(plan="pro").count()
    freeusers = User.query.filter_by(plan="free").count()
    yearly = User.query.filter(User.plan_is_annual == True).count()
    monthly = User.query.filter(User.plan_is_annual == False, User.plan != "free").count()

    mrr_m = (sum(1 for u in User.query.filter_by(plan="pro").filter_by(plan_is_annual=False).all()) * 29 +
             sum(1 for u in User.query.filter_by(plan="starter").filter_by(plan_is_annual=False).all()) * 9)
    mrr_y = (sum(1 for u in User.query.filter_by(plan="pro").filter_by(plan_is_annual=True).all()) * 290 / 12 +
              sum(1 for u in User.query.filter_by(plan="starter").filter_by(plan_is_annual=True).all()) * 90 / 12)
    mrr = mrr_m + mrr_y

    print("=== Seed Complete ===")
    print(f"Created: {created} users ({paying} paying + {freeusers} free)")
    print(f"Conversion rate: {paying/(paying+freeusers)*100:.1f}%")
    print(f"---")
    print(f"Total users: {total}")
    print(f"  Starter: {starters}")
    print(f"  Pro: {pros}")
    print(f"  Yearly: {yearly}")
    print(f"  Monthly: {monthly}")
    print(f"---")
    print(f"MRR (monthly): ${mrr_m:,}")
    print(f"MRR (yearly amortized): ${mrr_y:,.2f}")
    print(f"Total MRR: ${mrr:,.2f}")

    print(f"\n=== Join Date Distribution (10 months) ===")
    for mo in range(9, -1, -1):
        start = now - timedelta(days=(mo + 1) * 30)
        end = now - timedelta(days=mo * 30)
        all_c = User.query.filter(User.created_at >= start, User.created_at < end, User.role != "admin").count()
        paid_c = User.query.filter(User.created_at >= start, User.created_at < end, User.plan != "free").count()
        bar = "#" * (all_c // 8)
        label = f"Month -{mo+1}" if mo > 0 else "This month"
        print(f"  {label:12s}: {all_c:4d} users ({paid_c:3d} paid) {bar}")

    print(f"\nSample paying customers (by tier):")
    for u in User.query.filter(User.plan != "free").order_by(User.plan_is_annual, User.plan).limit(20).all():
        tier = ("yearly" if u.plan_is_annual else "monthly")
        print(f"  {u.email:42s} {u.plan:8s} {tier:7s} joined {u.created_at.strftime('%b %d, %Y')}")