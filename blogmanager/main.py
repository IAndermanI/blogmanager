"""
Blog Manager API — SQLite edition
===================================
POST   /api/blogs                        create blog
GET    /api/blogs                        list blogs
GET    /api/blogs/{blog_id}              get blog config
DELETE /api/blogs/{blog_id}              delete blog

POST   /api/blogs/{blog_id}/posts        add post
GET    /api/blogs/{blog_id}/posts        list posts
GET    /api/blogs/{blog_id}/posts/{slug} get post
DELETE /api/blogs/{blog_id}/posts/{slug} delete post

GET    /{blog_id}/                       landing page
GET    /{blog_id}/blog                   post list
GET    /{blog_id}/blog/{slug}            single post
"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from slugify import slugify
from datetime import datetime
from typing import Optional
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
import sqlite3, json, re, os

app = FastAPI(title="Blog Manager")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = "data/blogs.db"
Path("data").mkdir(exist_ok=True)

jinja = Environment(loader=FileSystemLoader("templates"), autoescape=True)

# ── DB ────────────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    with get_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS blogs (
            id            TEXT PRIMARY KEY,
            name          TEXT NOT NULL,
            tagline       TEXT NOT NULL,
            description   TEXT NOT NULL,
            niche         TEXT DEFAULT 'lifestyle',
            language      TEXT DEFAULT 'en',
            primary_color TEXT DEFAULT '#c4847a',
            accent_color  TEXT DEFAULT '#e8c4b8',
            bg_color      TEXT DEFAULT '#faf7f4',
            text_color    TEXT DEFAULT '#3d2b2b',
            telegram_channel TEXT DEFAULT NULL,
            created_at    TEXT NOT NULL
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

# ── Helpers ───────────────────────────────────────────────────────────────────

def make_excerpt(content: str, length: int = 160) -> str:
    clean = re.sub(r'\s+', ' ', content).strip()
    return clean[:length] + "..." if len(clean) > length else clean

def unique_slug(db, blog_id: str, base: str) -> str:
    slug, i = base, 1
    while db.execute("SELECT 1 FROM posts WHERE blog_id=? AND slug=?", (blog_id, slug)).fetchone():
        slug = f"{base}-{i}"
        i += 1
    return slug

def row_to_dict(row) -> dict:
    return dict(row) if row else None

TRANSLATIONS = {
    "en": {
        "read_blog":    "Read the blog →",
        "read_more":    "Read more",
        "coming_soon":  "Coming soon",
        "first_post":   "First post coming soon",
        "stay_tuned":   "Stay tuned for our first article.",
        "our_story":    "Our story.",
        "about":        "About",
        "latest_posts": "Latest posts",
        "view_all":     "View all →",
        "no_posts":     "No posts yet. Check back soon!",
        "all_posts":    "All posts",
        "back":         "← Back to all posts",
        "blog_nav":     "Blog",
        "about_nav":    "About",
    },
    "ru": {
        "read_blog":    "Читать блог →",
        "read_more":    "Читать далее",
        "coming_soon":  "Скоро",
        "first_post":   "Первый пост скоро",
        "stay_tuned":   "Следите за обновлениями.",
        "our_story":    "Наша история.",
        "about":        "О нас",
        "latest_posts": "Последние посты",
        "view_all":     "Все посты →",
        "no_posts":     "Постов пока нет. Заходите позже!",
        "all_posts":    "Все посты",
        "back":         "← Все посты",
        "blog_nav":     "Блог",
        "about_nav":    "О нас",
    },
}

def get_t(lang: str) -> dict:
    return TRANSLATIONS.get(lang, TRANSLATIONS["en"])

def render(template_name: str, **ctx) -> HTMLResponse:
    cfg = ctx.get("cfg", {})
    lang = cfg.get("language", "en") if isinstance(cfg, dict) else "en"
    ctx["t"] = get_t(lang)
    return HTMLResponse(jinja.get_template(template_name).render(**ctx))

# ── Models ────────────────────────────────────────────────────────────────────

class CreateBlog(BaseModel):
    id: str
    name: str
    tagline: str
    description: str
    niche: Optional[str] = "lifestyle"
    language: Optional[str] = "en"
    primary_color: Optional[str] = "#c4847a"
    accent_color: Optional[str] = "#e8c4b8"
    bg_color: Optional[str] = "#faf7f4"
    text_color: Optional[str] = "#3d2b2b"
    telegram_channel: Optional[str] = None

class UpdateBlog(BaseModel):
    name: Optional[str] = None
    tagline: Optional[str] = None
    description: Optional[str] = None
    niche: Optional[str] = None
    primary_color: Optional[str] = None
    accent_color: Optional[str] = None
    bg_color: Optional[str] = None
    text_color: Optional[str] = None
    telegram_channel: Optional[str] = None

class CreatePost(BaseModel):
    title: str
    content: str
    category: Optional[str] = None
    excerpt: Optional[str] = None

# ── API: Blogs ────────────────────────────────────────────────────────────────

@app.post("/api/blogs", status_code=201)
def create_blog(data: CreateBlog):
    blog_id = slugify(data.id)
    with get_db() as db:
        existing = db.execute("SELECT id FROM blogs WHERE id=?", (blog_id,)).fetchone()
        if existing:
            raise HTTPException(400, f"Blog '{blog_id}' already exists")
        db.execute("""
            INSERT INTO blogs (id, name, tagline, description, niche, language,
                               primary_color, accent_color, bg_color, text_color,
                               telegram_channel, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (blog_id, data.name, data.tagline, data.description,
              data.niche, data.language, data.primary_color, data.accent_color,
              data.bg_color, data.text_color, data.telegram_channel,
              datetime.utcnow().isoformat() + "Z"))
    return {"success": True, "blog_id": blog_id, "url": f"/{blog_id}/"}

@app.get("/api/blogs")
def list_blogs():
    with get_db() as db:
        rows = db.execute("""
            SELECT b.*, COUNT(p.id) as post_count
            FROM blogs b
            LEFT JOIN posts p ON p.blog_id = b.id
            GROUP BY b.id
            ORDER BY b.created_at DESC
        """).fetchall()
    return [dict(r) for r in rows]

@app.get("/api/blogs/{blog_id}")
def get_blog(blog_id: str):
    with get_db() as db:
        row = db.execute("SELECT * FROM blogs WHERE id=?", (blog_id,)).fetchone()
    if not row:
        raise HTTPException(404, f"Blog '{blog_id}' not found")
    return dict(row)

@app.patch("/api/blogs/{blog_id}")
def update_blog(blog_id: str, data: UpdateBlog):
    fields = {k: v for k, v in data.dict().items() if v is not None}
    if not fields:
        raise HTTPException(400, "No fields to update")
    set_clause = ", ".join(f"{k}=?" for k in fields)
    with get_db() as db:
        db.execute(f"UPDATE blogs SET {set_clause} WHERE id=?",
                   (*fields.values(), blog_id))
    return {"success": True}

@app.delete("/api/blogs/{blog_id}")
def delete_blog(blog_id: str):
    with get_db() as db:
        db.execute("DELETE FROM blogs WHERE id=?", (blog_id,))
    return {"success": True}

# ── API: Posts ────────────────────────────────────────────────────────────────

@app.post("/api/blogs/{blog_id}/posts", status_code=201)
def create_post(blog_id: str, data: CreatePost):
    with get_db() as db:
        blog = db.execute("SELECT * FROM blogs WHERE id=?", (blog_id,)).fetchone()
        if not blog:
            raise HTTPException(404, f"Blog '{blog_id}' not found")
        blog = dict(blog)

        base_slug = slugify(data.title)
        slug      = unique_slug(db, blog_id, base_slug)
        category  = data.category or blog.get("niche", "General").capitalize()
        excerpt   = data.excerpt or make_excerpt(data.content)
        now       = datetime.utcnow().isoformat() + "Z"

        db.execute("""
            INSERT INTO posts (blog_id, slug, title, content, category, excerpt, date)
            VALUES (?,?,?,?,?,?,?)
        """, (blog_id, slug, data.title, data.content, category, excerpt, now))

    return {"success": True, "slug": slug, "url": f"/{blog_id}/blog/{slug}"}

@app.get("/api/blogs/{blog_id}/posts")
def list_posts(blog_id: str):
    with get_db() as db:
        if not db.execute("SELECT 1 FROM blogs WHERE id=?", (blog_id,)).fetchone():
            raise HTTPException(404, f"Blog '{blog_id}' not found")
        rows = db.execute("""
            SELECT slug, title, category, excerpt, date
            FROM posts WHERE blog_id=?
            ORDER BY date DESC
        """, (blog_id,)).fetchall()
    return [dict(r) for r in rows]

@app.get("/api/blogs/{blog_id}/posts/{slug}")
def get_post(blog_id: str, slug: str):
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM posts WHERE blog_id=? AND slug=?", (blog_id, slug)
        ).fetchone()
    if not row:
        raise HTTPException(404, "Post not found")
    return dict(row)

@app.delete("/api/blogs/{blog_id}/posts/{slug}")
def delete_post(blog_id: str, slug: str):
    with get_db() as db:
        db.execute("DELETE FROM posts WHERE blog_id=? AND slug=?", (blog_id, slug))
    return {"success": True}

# ── Frontend ──────────────────────────────────────────────────────────────────

def get_blog_or_404(blog_id: str) -> dict:
    with get_db() as db:
        row = db.execute("SELECT * FROM blogs WHERE id=?", (blog_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Blog not found")
    return dict(row)

def get_posts(blog_id: str) -> list:
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM posts WHERE blog_id=? ORDER BY date DESC", (blog_id,)
        ).fetchall()
    return [dict(r) for r in rows]

@app.get("/{blog_id}", response_class=HTMLResponse)
@app.get("/{blog_id}/", response_class=HTMLResponse)
def blog_index(blog_id: str):
    cfg   = get_blog_or_404(blog_id)
    posts = get_posts(blog_id)
    return render("index.html", cfg=cfg, posts=posts, base=f"/{blog_id}")

@app.get("/{blog_id}/blog", response_class=HTMLResponse)
def blog_list(blog_id: str):
    cfg   = get_blog_or_404(blog_id)
    posts = get_posts(blog_id)
    return render("blog.html", cfg=cfg, posts=posts, base=f"/{blog_id}")

@app.get("/{blog_id}/blog/{slug}", response_class=HTMLResponse)
def blog_post(blog_id: str, slug: str):
    cfg = get_blog_or_404(blog_id)
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM posts WHERE blog_id=? AND slug=?", (blog_id, slug)
        ).fetchone()
    if not row:
        raise HTTPException(404, "Post not found")
    return render("post.html", cfg=cfg, post=dict(row), base=f"/{blog_id}")

@app.get("/")
def root():
    blogs = list_blogs()
    return {"blogs": [{"id": b["id"], "name": b["name"], "url": f"/{b['id']}/"} for b in blogs]}



# ── AI endpoints ──────────────────────────────────────────────────────────────

import httpx

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
AI_MODEL           = os.environ.get("AI_MODEL", "google/gemini-2.0-flash-exp:free")
OPENROUTER_URL     = "https://openrouter.ai/api/v1/chat/completions"

async def call_ai(system: str, user: str, max_tokens: int = 800) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type":  "application/json",
                "HTTP-Referer":  "https://blogmanager.local",
            },
            json={
                "model":      AI_MODEL,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user},
                ],
            },
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()

class AIBlogPrompt(BaseModel):
    prompt: str

class AIPostPrompt(BaseModel):
    prompt: str
    blog_id: str

@app.post("/api/ai/generate-blog")
async def ai_generate_blog(data: AIBlogPrompt):
    system = """You generate blog configuration JSON. 
Reply ONLY with valid JSON, no markdown, no explanation.
Schema:
{
  "id": "url-slug",
  "name": "Blog Name",
  "tagline": "Short catchy phrase (max 6 words)",
  "description": "3-4 paragraph about text. Use \\n between paragraphs.",
  "niche": "one word niche",
  "language": "en or ru",
  "primary_color": "#hexcolor",
  "accent_color": "#hexcolor (lighter)",
  "bg_color": "#hexcolor (very light or dark)",
  "text_color": "#hexcolor (contrasting to bg)"
}
Choose beautiful complementary colors that match the niche/mood."""

    raw = await call_ai(system, data.prompt, max_tokens=600)
    try:
        match = re.search(r'\{[\s\S]*\}', raw)
        result = json.loads(match.group(0))
        return result
    except Exception as e:
        raise HTTPException(500, f"AI returned invalid JSON: {raw[:200]}")

@app.post("/api/ai/generate-post")
async def ai_generate_post(data: AIPostPrompt):
    with get_db() as db:
        blog = db.execute("SELECT * FROM blogs WHERE id=?", (data.blog_id,)).fetchone()
    if not blog:
        raise HTTPException(404, "Blog not found")
    blog = dict(blog)

    system = f"""You are a content writer for '{blog["name"]}', a {blog["niche"]} blog.
Write in {blog["language"]}. Style: engaging, specific, no fluff. 150-250 words.
Reply ONLY with valid JSON, no markdown:
{{
  "title": "Post title",
  "content": "Full post text. Use \\n\\n between paragraphs.",
  "category": "Category name",
  "excerpt": "1-2 sentence summary"
}}"""

    raw = await call_ai(system, data.prompt, max_tokens=800)
    try:
        match = re.search(r'\{[\s\S]*\}', raw)
        result = json.loads(match.group(0))
        return result
    except Exception as e:
        raise HTTPException(500, f"AI returned invalid JSON: {raw[:200]}")

@app.get("/admin", response_class=HTMLResponse)
def admin_panel():
    with open("templates/admin.html", "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())