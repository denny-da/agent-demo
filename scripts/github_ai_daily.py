from __future__ import annotations

import json
import os
import smtplib
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = ROOT / "data" / "snapshot.json"
REPORT_PATH = ROOT / "reports" / "latest.md"
CN_TZ = timezone(timedelta(hours=8))

CATEGORIES = {
    "AI Agent": "topic:ai-agents",
    "Autonomous Agent": '"autonomous agent" in:name,description,readme',
    "Claude Skills": '("claude skill" OR "agent skill") in:name,description,readme',
    "MCP Server": '(mcp OR "model context protocol") in:name,description,readme',
    "RAG": '(rag OR "retrieval augmented generation") in:name,description,readme',
    "LLM 应用": '(llm OR "large language model") in:name,description,readme',
}


def github_json(path: str) -> dict:
    request = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
            "User-Agent": "github-ai-daily",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.load(response)


def translate_descriptions(repositories: list[dict]) -> None:
    """Translate only repositories that will appear in the report."""
    unique = {repo["name"]: repo for repo in repositories}
    items = [
        {"name": repo["name"], "description": repo["description"]}
        for repo in unique.values()
    ]
    for start in range(0, len(items), 10):
        batch = items[start : start + 10]
        payload = {
            "model": "openai/gpt-4.1",
            "temperature": 0.1,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是开源项目编辑。把每个 GitHub 项目简介翻译并改写为准确、自然、"
                        "简洁的一句中文，不添加原文没有的信息。只返回 JSON 数组，"
                        "每项严格使用 name 和 zh 两个字段。"
                    ),
                },
                {"role": "user", "content": json.dumps(batch, ensure_ascii=False)},
            ],
        }
        request = urllib.request.Request(
            "https://models.github.ai/inference/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2026-03-10",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                content = json.load(response)["choices"][0]["message"]["content"].strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0]
            for translated in json.loads(content):
                if translated.get("name") in unique and translated.get("zh"):
                    unique[translated["name"]]["description"] = translated["zh"].strip()
        except Exception as error:
            raise RuntimeError(f"中文翻译失败，已停止发送英文日报：{error}") from error


def search_repositories() -> dict[str, dict]:
    repositories: dict[str, dict] = {}
    for category, query in CATEGORIES.items():
        scoped_query = f"{query} stars:<60000 archived:false fork:false"
        params = urllib.parse.urlencode(
            {"q": scoped_query, "sort": "updated", "order": "desc", "per_page": 100}
        )
        payload = github_json(f"/search/repositories?{params}")
        for repo in payload.get("items", []):
            name = repo["full_name"]
            existing = repositories.get(name)
            if existing is None or repo["stargazers_count"] > existing["stars"]:
                repositories[name] = {
                    "name": name,
                    "url": repo["html_url"],
                    "stars": repo["stargazers_count"],
                    "language": repo.get("language") or "Unknown",
                    "description": (repo.get("description") or "无公开描述").strip(),
                    "created_at": repo["created_at"],
                    "updated_at": repo["updated_at"],
                    "category": category,
                }
        time.sleep(1)
    return repositories


def load_previous() -> dict:
    if not SNAPSHOT_PATH.exists():
        return {"repositories": {}}
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


def repo_line(repo: dict, metric: str) -> list[str]:
    return [
        f"- **[{repo['name']}]({repo['url']})** · ⭐{repo['stars']:,} · {metric} · `{repo['language']}`",
        f"  - 分类：{repo['category']}",
        f"  - {repo['description']}",
    ]


def generate_report(repositories: dict[str, dict], previous: dict) -> str:
    now = datetime.now(CN_TZ)
    previous_repos = previous.get("repositories", {})

    for name, repo in repositories.items():
        old = previous_repos.get(name)
        repo["daily_growth"] = repo["stars"] - old["stars"] if old else None

    comparable = [repo for repo in repositories.values() if repo["daily_growth"] is not None]
    growth = sorted(comparable, key=lambda item: item["daily_growth"], reverse=True)[:10]

    cutoff = now.astimezone(timezone.utc) - timedelta(days=30)
    recent = []
    for repo in repositories.values():
        created = datetime.fromisoformat(repo["created_at"].replace("Z", "+00:00"))
        if created >= cutoff:
            age_days = max(1, (now.astimezone(timezone.utc) - created).days + 1)
            repo["stars_per_day"] = repo["stars"] / age_days
            recent.append(repo)
    recent.sort(key=lambda item: item["stars_per_day"], reverse=True)

    new_radar = [repo for name, repo in repositories.items() if name not in previous_repos]
    new_radar.sort(key=lambda item: item["stars"], reverse=True)

    translate_descriptions(growth[:10] + recent[:10] + new_radar[:10])

    lines = [
        f"# GitHub AI 项目日报 · {now:%Y-%m-%d}",
        "",
        "> 监控分类：AI Agent、AI 工具、Autonomous Agent、Claude Skills、LLM 应用、MCP Server、RAG",
        f"> 本次扫描去重后共 {len(repositories)} 个仓库（聚焦 ⭐<60,000 的新兴项目）",
        "",
        "## 🚀 增长最快（对比昨日 Star 新增）",
        "",
    ]
    if growth:
        for repo in growth:
            lines.extend(repo_line(repo, f"📈 今日 {repo['daily_growth']:+,}"))
    else:
        lines.append("- 首次运行：暂无昨日独立快照，今天的数据将作为后续真实增量基线。")

    lines.extend(["", "## 🆕 最新出现（最近 30 天创建）", ""])
    for repo in recent[:10]:
        lines.extend(repo_line(repo, f"🔥 {repo['stars_per_day']:.1f}★/天"))
    if not recent:
        lines.append("- 本次扫描未发现符合条件且能核实创建日期的项目。")

    lines.extend(["", "## 📡 今日新进雷达（昨天还没出现的项目）", ""])
    for repo in new_radar[:10]:
        metric = "📈 首次记录" if repo["daily_growth"] is None else f"📈 今日 {repo['daily_growth']:+,}"
        lines.extend(repo_line(repo, metric))
    if not new_radar:
        lines.append("- 今日没有新进入监控集合的项目。")

    lines.extend(["", "---", f"*生成时间：{now:%Y-%m-%d %H:%M}（Asia/Shanghai）*", ""])
    return "\n".join(lines)


def send_email(report: str) -> None:
    username = os.environ.get("SMTP_USERNAME")
    password = os.environ.get("SMTP_APP_PASSWORD")
    recipient = os.environ.get("REPORT_RECIPIENT")
    if not username or not password or not recipient:
        raise RuntimeError("缺少 SMTP_USERNAME、SMTP_APP_PASSWORD 或 REPORT_RECIPIENT")

    today = datetime.now(CN_TZ).strftime("%Y-%m-%d")
    message = EmailMessage()
    message["Subject"] = f"GitHub AI 项目日报 · {today}"
    message["From"] = username
    message["To"] = recipient
    message.set_content(report)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=45) as smtp:
        smtp.login(username, password)
        smtp.send_message(message)


def main() -> None:
    repositories = search_repositories()
    previous = load_previous()
    report = generate_report(repositories, previous)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")

    snapshot = {
        "generated_at": datetime.now(CN_TZ).isoformat(),
        "repositories": repositories,
    }
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    send_email(report)
    print(report)


if __name__ == "__main__":
    main()
