"""
Blog Manager API — SQLite edition
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from slugify import slugify
from datetime import datetime
from typing import Optional, List
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
import sqlite3, json, re, os, httpx

app = FastAPI(title="Blog Manager")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DB_PATH = "data/blogs.db"
Path("data").mkdir(exist_ok=True)
jinja = Environment(loader=FileSystemLoader("templates"), autoescape=True)

# ── Markdown filter ───────────────────────────────────────────────────────────

def markdown_to_html(text: str) -> str:
    import html as hl
    # Обрабатываем маркеры фото [[PHOTO:url|author|authorUrl]]
    import re as _re
    def replace_photo(m):
        parts = m.group(1).split('|')
        url        = parts[0] if len(parts) > 0 else ''
        author     = parts[1] if len(parts) > 1 else ''
        author_url = parts[2] if len(parts) > 2 else ''
        credit = f'''<a href="{author_url}" target="_blank" rel="noopener">{hl.escape(author)}</a> / <a href="https://unsplash.com" target="_blank" rel="noopener">Unsplash</a>''' if author else '<a href="https://unsplash.com" target="_blank" rel="noopener">Unsplash</a>'
        return f'''<figure class="post-figure"><img src="{url}" alt="" loading="lazy" class="post-inline-photo"><figcaption class="post-photo-credit">Фото: {credit}</figcaption></figure>'''
    text = _re.sub(r'\[\[PHOTO:([^\]]+)\]\]', replace_photo, text)
    lines = text.split("\n")
    result = []
    in_list = False
    for line in lines:
        s = line.strip()
        if not s:
            if in_list: result.append("</ul>"); in_list = False
            result.append("")
            continue
        if s.startswith("## "):
            if in_list: result.append("</ul>"); in_list = False
            result.append(f"<h2>{hl.escape(s[3:])}</h2>"); continue
        if s.startswith("### "):
            if in_list: result.append("</ul>"); in_list = False
            result.append(f"<h3>{hl.escape(s[4:])}</h3>"); continue
        if s.startswith("- ") or s.startswith("* "):
            if not in_list: result.append("<ul>"); in_list = True
            c = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", hl.escape(s[2:]))
            result.append(f"<li>{c}</li>"); continue
        if in_list: result.append("</ul>"); in_list = False
        # Картинка ![alt](url)
        img_match = re.match(r'^!\[([^\]]*)\]\(([^)]+)\)$', s)
        if img_match:
            alt, src = img_match.group(1), img_match.group(2)
            result.append(f'<img src="{hl.escape(src)}" alt="{hl.escape(alt)}" class="post-inline-img" loading="lazy">')
            continue
        c = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", hl.escape(s))
        result.append(f"<p>{c}</p>")
    if in_list: result.append("</ul>")
    return "\n".join(result)

jinja.filters["markdown"] = markdown_to_html

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
            system_prompt    TEXT DEFAULT NULL,
            topic_prompt     TEXT DEFAULT NULL,
            theme            TEXT DEFAULT 'feminine',
            created_at       TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS posts (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            blog_id   TEXT NOT NULL REFERENCES blogs(id) ON DELETE CASCADE,
            slug      TEXT NOT NULL,
            title     TEXT NOT NULL,
            content   TEXT NOT NULL,
            category  TEXT DEFAULT 'General',
            excerpt        TEXT,
            photo_url      TEXT DEFAULT NULL,
            photo_author    TEXT DEFAULT NULL,
            photo_author_url TEXT DEFAULT NULL,
            date      TEXT NOT NULL,
            UNIQUE(blog_id, slug)
        );
        CREATE INDEX IF NOT EXISTS idx_posts_blog ON posts(blog_id);
        """)
        # Migrate existing DBs
        for col, defn in [
            ("system_prompt", "TEXT DEFAULT NULL"),
            ("topic_prompt",  "TEXT DEFAULT NULL"),
            ("theme",         "TEXT DEFAULT 'feminine'"),
        ]:
            try:
                db.execute(f"ALTER TABLE blogs ADD COLUMN {col} {defn}")
                db.commit()
            except Exception:
                pass
        for col, defn in [
            ("photo_url",       "TEXT DEFAULT NULL"),
            ("photo_author",    "TEXT DEFAULT NULL"),
            ("photo_author_url","TEXT DEFAULT NULL"),
        ]:
            try:
                db.execute(f"ALTER TABLE blogs ADD COLUMN {col} {defn}")
                db.commit()
            except Exception:
                pass

init_db()

# ── Helpers ───────────────────────────────────────────────────────────────────

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
        "stay_tuned": "Stay tuned.", "our_story": "Our story.", "about": "About",
        "latest_posts": "Latest posts", "view_all": "View all →",
        "no_posts": "No posts yet. Check back soon!",
        "all_posts": "All posts", "back": "← Back to all posts",
        "blog_nav": "Blog", "about_nav": "About",
    },
    "ru": {
        "read_blog": "Читать блог →", "read_more": "Читать далее",
        "coming_soon": "Скоро", "first_post": "Первый пост скоро",
        "stay_tuned": "Следите за обновлениями.", "our_story": "Наша история.", "about": "О нас",
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

def get_recent_titles(blog_id: str, limit: int = 15) -> list:
    with get_db() as db:
        rows = db.execute(
            "SELECT title FROM posts WHERE blog_id=? ORDER BY date DESC LIMIT ?",
            (blog_id, limit)
        ).fetchall()
    return [r["title"] for r in rows]

# ── Models ────────────────────────────────────────────────────────────────────

class CreateBlog(BaseModel):
    id: str; name: str; tagline: str; description: str
    niche: Optional[str] = "lifestyle"; language: Optional[str] = "en"
    primary_color: Optional[str] = "#c4847a"; accent_color: Optional[str] = "#e8c4b8"
    bg_color: Optional[str] = "#faf7f4"; text_color: Optional[str] = "#3d2b2b"
    telegram_channel: Optional[str] = None
    system_prompt: Optional[str] = None
    topic_prompt: Optional[str] = None
    theme: Optional[str] = "feminine"

class UpdateBlog(BaseModel):
    name: Optional[str] = None; tagline: Optional[str] = None
    description: Optional[str] = None; niche: Optional[str] = None
    primary_color: Optional[str] = None; accent_color: Optional[str] = None
    bg_color: Optional[str] = None; text_color: Optional[str] = None
    telegram_channel: Optional[str] = None
    system_prompt: Optional[str] = None
    topic_prompt: Optional[str] = None
    theme: Optional[str] = None

class CreatePost(BaseModel):
    title: str; content: str
    category: Optional[str] = None; excerpt: Optional[str] = None
    photo_url: Optional[str] = None
    photo_author: Optional[str] = None
    photo_author_url: Optional[str] = None

class AIBlogPrompt(BaseModel):
    prompt: str

class AIPostPrompt(BaseModel):
    prompt: str
    blog_id: str

class TriggerPostRequest(BaseModel):
    blog_id: str
    hint: Optional[str] = None  # доп. пожелание по теме (опционально)

# ── AI ────────────────────────────────────────────────────────────────────────

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

# ── Default prompts (редактируются в admin → Advanced Settings) ───────────────

DEFAULT_PROMPTS = {
    "system_prompt_ru": (
        "Пиши как умный друг, который хорошо разбирается в теме.\n"
        "Живой разговорный русский. Никакого канцелярита.\n"
        "Никаких кавычек вокруг обычных слов.\n"
        "Короткие предложения приветствуются."
    ),
    "system_prompt_en": (
        "Write like a knowledgeable friend explaining something over coffee.\n"
        "Warm, direct, no corporate speak. Real person who knows their stuff."
    ),
    "topic_prompt": (
        "Choose a topic that:\n"
        "- Hasn't been covered in recent posts\n"
        "- Fits the current season or moment if relevant\n"
        "- Has a specific, counter-intuitive, or surprising angle\n"
        "- Is genuinely useful or interesting to the target audience\n"
        "- Avoid generic titles like 'Top 10 tips' or 'How to get started'"
    ),
    "generate_blog_system": (
        "You generate blog configuration JSON.\n"
        "Reply ONLY with valid JSON, no markdown, no explanation.\n"
        "Schema: {\"id\":\"url-slug\",\"name\":\"Blog Name\","
        "\"tagline\":\"Short phrase (max 6 words)\","
        "\"description\":\"3-4 paragraphs. Use \\n between them.\","
        "\"niche\":\"one word\",\"language\":\"en or ru\","
        "\"primary_color\":\"#hex\",\"accent_color\":\"#hex lighter\","
        "\"bg_color\":\"#hex very light\",\"text_color\":\"#hex contrasting\"}\n"
        "Choose beautiful colors matching the niche/mood.\n"
        "Description must feel personal and real — not marketing copy.\n"
        "No 'welcome to our blog' or 'here you will find'.\n"
        "Tagline: punchy and memorable."
    ),
}
AI_MODEL = os.environ.get("AI_MODEL", "google/gemini-2.0-flash-exp:free")
N8N_WEBHOOK_URL = os.environ.get("N8N_WEBHOOK_URL", "")
N8N_CREATE_POST_WEBHOOK = os.environ.get("N8N_CREATE_POST_WEBHOOK", "")

async def call_ai(system: str, user: str, max_tokens: int = 800) -> str:
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://blogmanager.local",
            },
            json={
                "model": AI_MODEL,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user},
                ],
            },
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()

# ── Static routes ─────────────────────────────────────────────────────────────

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

# ── API: Blogs ────────────────────────────────────────────────────────────────

@app.post("/api/blogs", status_code=201)
def create_blog(data: CreateBlog):
    blog_id = slugify(data.id)
    with get_db() as db:
        if db.execute("SELECT 1 FROM blogs WHERE id=?", (blog_id,)).fetchone():
            raise HTTPException(400, f"Blog '{blog_id}' already exists")
        db.execute(
            """INSERT INTO blogs
               (id,name,tagline,description,niche,language,
                primary_color,accent_color,bg_color,text_color,
                telegram_channel,system_prompt,topic_prompt,theme,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (blog_id, data.name, data.tagline, data.description,
             data.niche, data.language,
             data.primary_color, data.accent_color, data.bg_color, data.text_color,
             data.telegram_channel, data.system_prompt, data.topic_prompt,
             data.theme or "feminine", datetime.utcnow().isoformat()+"Z")
        )
    return {"success": True, "blog_id": blog_id, "url": f"/{blog_id}/"}

@app.get("/api/blogs")
def list_blogs():
    with get_db() as db:
        rows = db.execute("""
            SELECT b.*, COUNT(p.id) as post_count
            FROM blogs b LEFT JOIN posts p ON p.blog_id=b.id
            GROUP BY b.id ORDER BY b.created_at DESC
        """).fetchall()
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

# ── API: Posts ────────────────────────────────────────────────────────────────

@app.post("/api/blogs/{blog_id}/posts", status_code=201)
def create_post(blog_id: str, data: CreatePost):
    with get_db() as db:
        blog = db.execute("SELECT * FROM blogs WHERE id=?", (blog_id,)).fetchone()
        if not blog: raise HTTPException(404, f"Blog '{blog_id}' not found")
        blog = dict(blog)
        slug = unique_slug(db, blog_id, slugify(data.title))
        db.execute(
            "INSERT INTO posts (blog_id,slug,title,content,category,excerpt,photo_url,photo_author,photo_author_url,date) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (blog_id, slug, data.title, data.content,
             data.category or blog.get("niche", "General").capitalize(),
             data.excerpt or make_excerpt(data.content),
             data.photo_url, data.photo_author, data.photo_author_url,
             datetime.utcnow().isoformat()+"Z")
        )
    return {"success": True, "slug": slug, "url": f"/{blog_id}/blog/{slug}"}

@app.get("/api/blogs/{blog_id}/posts")
def list_posts(blog_id: str):
    with get_db() as db:
        if not db.execute("SELECT 1 FROM blogs WHERE id=?", (blog_id,)).fetchone():
            raise HTTPException(404, f"Blog '{blog_id}' not found")
        rows = db.execute(
            "SELECT slug,title,category,excerpt,date FROM posts WHERE blog_id=? ORDER BY date DESC",
            (blog_id,)
        ).fetchall()
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

# ── API: AI ───────────────────────────────────────────────────────────────────

@app.post("/api/ai/generate-blog")
async def ai_generate_blog(data: AIBlogPrompt):
    raw = await call_ai(DEFAULT_PROMPTS["generate_blog_system"], data.prompt, 700)
    try:
        return json.loads(re.search(r'\{[\s\S]*\}', raw).group(0))
    except:
        raise HTTPException(500, f"AI returned invalid JSON: {raw[:200]}")

@app.post("/api/ai/generate-post")
async def ai_generate_post(data: AIPostPrompt):
    """Прямая генерация поста из админки (без n8n)."""
    blog = get_blog_or_404(data.blog_id)
    recent_titles = get_recent_titles(data.blog_id)
    lang = blog.get("language", "en")
    voice = (blog.get("system_prompt") or "").strip()
    if not voice:
        voice = DEFAULT_PROMPTS["system_prompt_ru"] if lang == "ru" else DEFAULT_PROMPTS["system_prompt_en"]
    topic_rules = (blog.get("topic_prompt") or "").strip() or DEFAULT_PROMPTS["topic_prompt"]
    recent_block = "\n".join(f"- {t}" for t in (recent_titles or [])[:15])
    recent_section = f"Recent posts (DO NOT repeat):\n{recent_block}" if recent_block else ""
    lang_instr = "Write entirely in Russian." if lang == "ru" else "Write entirely in English."
    system = "\n\n".join(filter(bool, [
        f'You are the lead writer for "{blog["name"]}", a {blog["niche"]} blog.',
        lang_instr,
        f"BLOG VOICE:\n{voice}",
        f"TOPIC SELECTION:\n{topic_rules}",
        recent_section,
        "CONTENT REQUIREMENTS:\n"
        "- Length: 600-900 words minimum.\n"
        "- Structure: hook → context → main content → actionable takeaway → closing thought.\n"
        "- Hook: surprising fact, relatable problem, or bold statement.\n"
        "  NEVER start with \"In this article...\" / \"Today we will...\" / \"В этой статье...\"\n"
        "- Specific details, numbers, real examples. Vague advice is useless.\n"
        "- Subheadings: standalone lines, no symbols, spark curiosity.\n"
        "- End with a takeaway or thought-provoking question.\n"
        "- 2-4 emojis placed naturally. NO hashtags.\n\n"
        "FORMATTING — plain text only:\n"
        "- Paragraphs separated by blank line\n"
        "- Subheadings as standalone lines (NO ##, NO **, NO HTML)\n"
        "- NO markdown, NO quotes around ordinary words\n\n"
        "TONE — avoid: \"В заключение\", \"In conclusion\", filler openers, passive voice\n\n"
        "Reply ONLY with valid JSON:\n"
        '{"title":"...","content":"...min 600 words, plain text, \\n\\n between paragraphs","category":"...","excerpt":"..."}'
    ]))
    raw = await call_ai(system, data.prompt or "Generate a fresh post for this blog.", 2000)
    try:
        return json.loads(re.search(r'\{[\s\S]*\}', raw).group(0))
    except:
        raise HTTPException(500, f"AI returned invalid JSON: {raw[:200]}")

@app.post("/api/trigger/create-post")
async def trigger_create_post(data: TriggerPostRequest):
    """
    Запускает n8n граф 'Create Post' для конкретного блога.
    Передаёт блог + последние заголовки + опциональный hint.
    n8n сам генерирует пост, сохраняет и публикует в Telegram.
    """
    if not N8N_CREATE_POST_WEBHOOK:
        raise HTTPException(503, "N8N_CREATE_POST_WEBHOOK not configured")

    blog = get_blog_or_404(data.blog_id)
    recent_titles = get_recent_titles(data.blog_id)

    now = datetime.utcnow()
    payload = {
        "blog": blog,
        "recent_titles": recent_titles,
        "date_str": now.strftime("%A, %B %d, %Y"),
        "hint": data.hint or "",
    }

    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(N8N_CREATE_POST_WEBHOOK, json=payload)

    return {"success": True, "status": r.status_code}

# ── API: Prompts ─────────────────────────────────────────────────────────────

@app.get("/api/prompts")
def get_prompts():
    """
    Дефолтные промпты — используются как fallback в n8n и как placeholder в админке.
    GET http://172.17.0.1:8000/api/prompts
    """
    return DEFAULT_PROMPTS

# ── Frontend ──────────────────────────────────────────────────────────────────

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