"""
Blog Manager API — SQLite edition
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from slugify import slugify
from datetime import datetime
from typing import Optional
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
import sqlite3, json, re, os, httpx

app = FastAPI(title="Blog Manager")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DB_PATH = "data/blogs.db"
Path("data").mkdir(exist_ok=True)
jinja = Environment(loader=FileSystemLoader("templates"), autoescape=True)

def markdown_to_html(text: str) -> str:
    """Minimal markdown: ## headings, **bold**, - bullet lists."""
    import html as html_lib
    lines = text.split("\n")
    result = []
    in_list = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_list:
                result.append("<\/ul>")
                in_list = False
            result.append("")
            continue
        if stripped.startswith("## "):
            if in_list: result.append("<\/ul>"); in_list = False
            result.append(f"<h2>{html_lib.escape(stripped[3:])}<\/h2>")
            continue
        if stripped.startswith("### "):
            if in_list: result.append("<\/ul>"); in_list = False
            result.append(f"<h3>{html_lib.escape(stripped[4:])}<\/h3>")
            continue
        if stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list:
                result.append("<ul>")
                in_list = True
            c = html_lib.escape(stripped[2:])
            c = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1<\/strong>", c)
            result.append(f"<li>{c}<\/li>")
            continue
        if in_list: result.append("<\/ul>"); in_list = False
        c = html_lib.escape(stripped)
        c = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1<\/strong>", c)
        result.append(f"<p>{c}<\/p>")
    if in_list: result.append("<\/ul>")
    return "\n".join(result)

jinja.filters["markdown"] = markdown_to_html

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    with get_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS blogs (
            id               TEXT PRIMARY KEY,
            name             TEXT NOT NULL,
            tagline          TEXT NOT NULL,
            description      TEXT NOT NULL,
            niche            TEXT DEFAULT 'lifestyle',
            language         TEXT DEFAULT 'en',
            primary_color    TEXT DEFAULT '#c4847a',
            accent_color     TEXT DEFAULT '#e8c4b8',
            bg_color         TEXT DEFAULT '#faf7f4',
            text_color       TEXT DEFAULT '#3d2b2b',
            telegram_channel TEXT DEFAULT NULL,
            created_at       TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS posts (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            blog_id   TEXT NOT NULL REFERENCES blogs(id) ON DELETE CASCADE,
            slug      TEXT NOT NULL,
            title     TEXT NOT NULL,
            content   TEXT NOT NULL,
            category  TEXT DEFAULT 'General',
            excerpt   TEXT,
            date      TEXT NOT NULL,
            UNIQUE(blog_id, slug)
        );
        CREATE INDEX IF NOT EXISTS idx_posts_blog ON posts(blog_id);
        """)

init_db()

def make_excerpt(content: str, length: int = 160) -> str:
    clean = re.sub(r'\s+', ' ', content).strip()
    return clean[:length] + "..." if len(clean) > length else clean

def unique_slug(db, blog_id: str, base: str) -> str:
    slug, i = base, 1
    while db.execute("SELECT 1 FROM posts WHERE blog_id=? AND slug=?", (blog_id, slug)).fetchone():
        slug = f"{base}-{i}"; i += 1
    return slug

TRANSLATIONS = {
    "en": {
        "read_blog": "Read the blog →", "read_more": "Read more",
        "coming_soon": "Coming soon", "first_post": "First post coming soon",
        "stay_tuned": "Stay tuned for our first article.",
        "our_story": "Our story.", "about": "About",
        "latest_posts": "Latest posts", "view_all": "View all →",
        "no_posts": "No posts yet. Check back soon!",
        "all_posts": "All posts", "back": "← Back to all posts",
        "blog_nav": "Blog", "about_nav": "About",
    },
    "ru": {
        "read_blog": "Читать блог →", "read_more": "Читать далее",
        "coming_soon": "Скоро", "first_post": "Первый пост скоро",
        "stay_tuned": "Следите за обновлениями.",
        "our_story": "Наша история.", "about": "О нас",
        "latest_posts": "Последние посты", "view_all": "Все посты →",
        "no_posts": "Постов пока нет. Заходите позже!",
        "all_posts": "Все посты", "back": "← Все посты",
        "blog_nav": "Блог", "about_nav": "О нас",
    },
}

def get_t(lang): return TRANSLATIONS.get(lang, TRANSLATIONS["en"])

def render(template_name, **ctx):
    cfg = ctx.get("cfg", {})
    lang = cfg.get("language", "en") if isinstance(cfg, dict) else "en"
    ctx["t"] = get_t(lang)
    return HTMLResponse(jinja.get_template(template_name).render(**ctx))

def get_blog_or_404(blog_id):
    with get_db() as db:
        row = db.execute("SELECT * FROM blogs WHERE id=?", (blog_id,)).fetchone()
    if not row: raise HTTPException(404, "Blog not found")
    return dict(row)

def get_posts_list(blog_id):
    with get_db() as db:
        rows = db.execute("SELECT * FROM posts WHERE blog_id=? ORDER BY date DESC", (blog_id,)).fetchall()
    return [dict(r) for r in rows]

# Models
class CreateBlog(BaseModel):
    id: str; name: str; tagline: str; description: str
    niche: Optional[str] = "lifestyle"; language: Optional[str] = "en"
    primary_color: Optional[str] = "#c4847a"; accent_color: Optional[str] = "#e8c4b8"
    bg_color: Optional[str] = "#faf7f4"; text_color: Optional[str] = "#3d2b2b"
    telegram_channel: Optional[str] = None

class UpdateBlog(BaseModel):
    name: Optional[str] = None; tagline: Optional[str] = None
    description: Optional[str] = None; niche: Optional[str] = None
    primary_color: Optional[str] = None; accent_color: Optional[str] = None
    bg_color: Optional[str] = None; text_color: Optional[str] = None
    telegram_channel: Optional[str] = None

class CreatePost(BaseModel):
    title: str; content: str
    category: Optional[str] = None; excerpt: Optional[str] = None

class AIBlogPrompt(BaseModel): prompt: str
class AIPostPrompt(BaseModel): prompt: str; blog_id: str

# AI
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
AI_MODEL = os.environ.get("AI_MODEL", "google/gemini-2.0-flash-exp:free")

async def call_ai(system, user, max_tokens=800):
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
            json={"model": AI_MODEL, "max_tokens": max_tokens,
                  "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()

# ── STATIC ROUTES (before /{blog_id}) ────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def root():
    with get_db() as db:
        rows = db.execute("SELECT id, name FROM blogs ORDER BY created_at DESC").fetchall()
    links = "".join(f'<li><a href="/{r["id"]}/">{r["name"]}</a></li>' for r in rows)
    return HTMLResponse(f"<h2>Blogs</h2><ul>{links}</ul><p><a href='/admin'>Admin →</a></p>")

@app.get("/admin", response_class=HTMLResponse)
def admin_panel():
    with open("templates/admin.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())

# ── API Blogs ─────────────────────────────────────────────────────────────────

@app.post("/api/blogs", status_code=201)
def create_blog(data: CreateBlog):
    blog_id = slugify(data.id)
    with get_db() as db:
        if db.execute("SELECT 1 FROM blogs WHERE id=?", (blog_id,)).fetchone():
            raise HTTPException(400, f"Blog '{blog_id}' already exists")
        db.execute("""INSERT INTO blogs (id,name,tagline,description,niche,language,
            primary_color,accent_color,bg_color,text_color,telegram_channel,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (blog_id, data.name, data.tagline, data.description, data.niche, data.language,
             data.primary_color, data.accent_color, data.bg_color, data.text_color,
             data.telegram_channel, datetime.utcnow().isoformat()+"Z"))
    return {"success": True, "blog_id": blog_id, "url": f"/{blog_id}/"}

@app.get("/api/blogs")
def list_blogs():
    with get_db() as db:
        rows = db.execute("""SELECT b.*, COUNT(p.id) as post_count
            FROM blogs b LEFT JOIN posts p ON p.blog_id=b.id
            GROUP BY b.id ORDER BY b.created_at DESC""").fetchall()
    return [dict(r) for r in rows]

@app.get("/api/blogs/{blog_id}")
def get_blog(blog_id: str):
    with get_db() as db:
        row = db.execute("SELECT * FROM blogs WHERE id=?", (blog_id,)).fetchone()
    if not row: raise HTTPException(404, f"Blog '{blog_id}' not found")
    return dict(row)

@app.patch("/api/blogs/{blog_id}")
def update_blog(blog_id: str, data: UpdateBlog):
    fields = {k: v for k, v in data.dict().items() if v is not None}
    if not fields: raise HTTPException(400, "No fields to update")
    set_clause = ", ".join(f"{k}=?" for k in fields)
    with get_db() as db:
        db.execute(f"UPDATE blogs SET {set_clause} WHERE id=?", (*fields.values(), blog_id))
    return {"success": True}

@app.delete("/api/blogs/{blog_id}")
def delete_blog(blog_id: str):
    with get_db() as db:
        db.execute("DELETE FROM blogs WHERE id=?", (blog_id,))
    return {"success": True}

# ── API Posts ─────────────────────────────────────────────────────────────────

@app.post("/api/blogs/{blog_id}/posts", status_code=201)
def create_post(blog_id: str, data: CreatePost):
    with get_db() as db:
        blog = db.execute("SELECT * FROM blogs WHERE id=?", (blog_id,)).fetchone()
        if not blog: raise HTTPException(404, f"Blog '{blog_id}' not found")
        blog = dict(blog)
        slug = unique_slug(db, blog_id, slugify(data.title))
        db.execute("INSERT INTO posts (blog_id,slug,title,content,category,excerpt,date) VALUES (?,?,?,?,?,?,?)",
            (blog_id, slug, data.title, data.content,
             data.category or blog.get("niche","General").capitalize(),
             data.excerpt or make_excerpt(data.content),
             datetime.utcnow().isoformat()+"Z"))
    return {"success": True, "slug": slug, "url": f"/{blog_id}/blog/{slug}"}

@app.get("/api/blogs/{blog_id}/posts")
def list_posts(blog_id: str):
    with get_db() as db:
        if not db.execute("SELECT 1 FROM blogs WHERE id=?", (blog_id,)).fetchone():
            raise HTTPException(404, f"Blog '{blog_id}' not found")
        rows = db.execute("SELECT slug,title,category,excerpt,date FROM posts WHERE blog_id=? ORDER BY date DESC", (blog_id,)).fetchall()
    return [dict(r) for r in rows]

@app.get("/api/blogs/{blog_id}/posts/{slug}")
def get_post(blog_id: str, slug: str):
    with get_db() as db:
        row = db.execute("SELECT * FROM posts WHERE blog_id=? AND slug=?", (blog_id, slug)).fetchone()
    if not row: raise HTTPException(404, "Post not found")
    return dict(row)

@app.delete("/api/blogs/{blog_id}/posts/{slug}")
def delete_post(blog_id: str, slug: str):
    with get_db() as db:
        db.execute("DELETE FROM posts WHERE blog_id=? AND slug=?", (blog_id, slug))
    return {"success": True}

# ── AI endpoints ──────────────────────────────────────────────────────────────

@app.post("/api/ai/generate-blog")
async def ai_generate_blog(data: AIBlogPrompt):
    system = """You generate blog configuration JSON.
Reply ONLY with valid JSON, no markdown, no explanation.
Schema: {"id":"url-slug","name":"Blog Name","tagline":"Short phrase (max 6 words)",
"description":"3-4 paragraphs. Use \\n between them.","niche":"one word",
"language":"en or ru","primary_color":"#hex","accent_color":"#hex lighter",
"bg_color":"#hex very light","text_color":"#hex contrasting"}
Choose beautiful colors matching the niche/mood.
The description must feel personal and real — like a human editor wrote it, not a marketing bot.
Avoid generic phrases like 'welcome to our blog' or 'here you will find'. Be specific about the niche and the audience."""
    raw = await call_ai(system, data.prompt, 700)
    try:
        return json.loads(re.search(r'\{[\s\S]*\}', raw).group(0))
    except:
        raise HTTPException(500, f"AI returned invalid JSON: {raw[:200]}")

@app.post("/api/ai/generate-post")
async def ai_generate_post(data: AIPostPrompt):
    with get_db() as db:
        blog = db.execute("SELECT * FROM blogs WHERE id=?", (data.blog_id,)).fetchone()
    if not blog: raise HTTPException(404, "Blog not found")
    blog = dict(blog)
    lang_instruction = (
        "Write entirely in Russian. Use natural, conversational Russian — not formal or translated-sounding."
        if blog["language"] == "ru"
        else "Write entirely in English. Use a warm, direct tone — like a knowledgeable friend, not a copywriter."
    )
    system = f"""You are the lead writer for "{blog["name"]}", a {blog["niche"]} blog.
{lang_instruction}

CONTENT REQUIREMENTS:
- Length: 600-900 words minimum. Short posts will be rejected.
- Structure: hook → context → main content (with subheadings) → actionable takeaway → closing thought.
- Start with a strong hook: a surprising fact, a relatable problem, or a bold statement. NEVER start with "In this article..." or "Today we will..."
- Use specific details, numbers, real examples. Vague advice is useless.
- Every paragraph must deliver value. No filler sentences.
- Subheadings should read as natural sentences that spark curiosity (not "Step 1:" or "Introduction").
- End with a concrete takeaway or a thought-provoking question for the reader.

FORMATTING (use inside the content JSON field):
- \\n\\n between paragraphs
- ## before each subheading
- **bold** for key terms (max 2-3 per post)
- Bullet lists using - for steps or comparisons (optional)

TONE RULES — strictly avoid:
- "In conclusion", "It is important to note", "As we can see", "In today's world"
- Filler openers like "Are you looking for...", "Have you ever wondered..."
- Passive voice where active is possible
- Saying "you might want to consider" instead of just "do X"

Reply ONLY with valid JSON, no markdown wrapper, no extra text:
{{"title":"Specific, compelling title — not generic","content":"Full post, minimum 600 words, following all requirements. Use \\n\\n for paragraphs and ## for subheadings.","category":"Specific category","excerpt":"2-3 sentences that hook the reader. Include one specific detail or surprising fact from the post."}}"""
    raw = await call_ai(system, data.prompt, 2000)
    try:
        return json.loads(re.search(r'\{[\s\S]*\}', raw).group(0))
    except:
        raise HTTPException(500, f"AI returned invalid JSON: {raw[:200]}")

# ── Frontend (MUST be last) ───────────────────────────────────────────────────

@app.get("/{blog_id}", response_class=HTMLResponse)
@app.get("/{blog_id}/", response_class=HTMLResponse)
def blog_index(blog_id: str):
    return render("index.html", cfg=get_blog_or_404(blog_id), posts=get_posts_list(blog_id), base=f"/{blog_id}")

@app.get("/{blog_id}/blog", response_class=HTMLResponse)
def blog_list(blog_id: str):
    return render("blog.html", cfg=get_blog_or_404(blog_id), posts=get_posts_list(blog_id), base=f"/{blog_id}")

@app.get("/{blog_id}/blog/{slug}", response_class=HTMLResponse)
def blog_post(blog_id: str, slug: str):
    cfg = get_blog_or_404(blog_id)
    with get_db() as db:
        row = db.execute("SELECT * FROM posts WHERE blog_id=? AND slug=?", (blog_id, slug)).fetchone()
    if not row: raise HTTPException(404, "Post not found")
    return render("post.html", cfg=cfg, post=dict(row), base=f"/{blog_id}")