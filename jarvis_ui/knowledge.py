"""Local document indexing and keyword retrieval. No document bytes leave this process."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

SUPPORTED = {".md", ".txt", ".pdf"}
STOP_WORDS = set("a an and are as at be by for from has have how i in is it its me my of on or our the their this to was we what when where which who why with you your do does about into onto per tell show find".split())
WORD_RE = re.compile(r"[\w'-]+", re.UNICODE)


def tokenize(text):
    return [word.casefold() for word in WORD_RE.findall(text) if len(word) > 1 and word.casefold() not in STOP_WORDS]


def chunk_text(text, max_words=500, overlap=60):
    """Split text into bounded word chunks with a small overlap."""
    words = text.split()
    if not words:
        return []
    max_words = max(1, int(max_words))
    overlap = max(0, min(int(overlap), max_words - 1))
    stride = max_words - overlap
    return [" ".join(words[start:start + max_words]) for start in range(0, len(words), stride)]


def _extract_text(path):
    if path.suffix.casefold() != ".pdf":
        return path.read_text(encoding="utf-8", errors="replace")
    executable = shutil.which("pdftotext")
    if not executable:
        raise RuntimeError("pdftotext is required to read PDF files")
    result = subprocess.run(
        [executable, "-layout", str(path), "-"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=True,
    )
    return result.stdout


def _summary(text, limit=400):
    clean = " ".join(text.split())
    sentences = re.split(r"(?<=[.!?])\s+", clean)
    return " ".join(sentences[:2])[:limit]


def _file_record(path, root, raw):
    text = _extract_text(path)
    chunks = chunk_text(text)
    terms = Counter(tokenize(text))
    relative = path.relative_to(root).as_posix()
    stat = path.stat()
    return {
        "path": relative,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "mtime": stat.st_mtime,
        "mtime_ns": stat.st_mtime_ns,
        "size": stat.st_size,
        "word_count": len(text.split()),
        "summary": _summary(text),
        "keywords": [word for word, _ in terms.most_common(24)],
        "chunks": chunks,
    }


def load_index(index_file):
    try:
        payload = json.loads(Path(index_file).read_text(encoding="utf-8"))
        files = payload.get("files", {})
        return files if isinstance(files, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def _write_index(index_file, files):
    target = Path(index_file)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, prefix=".jarvis-index-", suffix=".tmp", delete=False) as temp:
        json.dump({"version": 1, "files": files}, temp, ensure_ascii=False, indent=2)
        temp.write("\n")
        temp_path = Path(temp.name)
    temp_path.replace(target)


def build_index(directory, index_file, progress=None):
    """Re-index only files whose SHA-256 changed; delete stale index entries, never source files."""
    root = Path(directory).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    old_files = load_index(index_file)
    paths = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.casefold() in SUPPORTED)
    total = len(paths)
    indexed = {}
    errors = []
    changed, unchanged = 0, 0
    if progress:
        progress(0, total, "")
    for done, path in enumerate(paths, 1):
        relative = path.relative_to(root).as_posix()
        try:
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            old = old_files.get(relative)
            if old and old.get("sha256") == digest:
                indexed[relative] = old
                unchanged += 1
            else:
                indexed[relative] = _file_record(path, root, raw)
                changed += 1
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            errors.append({"file": relative, "error": type(exc).__name__})
            if relative in old_files:
                indexed[relative] = old_files[relative]
        if progress:
            progress(done, total, relative)
    removed = len(set(old_files) - set(indexed))
    _write_index(index_file, indexed)
    return {"total": total, "changed": changed, "unchanged": unchanged, "removed": removed, "errors": errors, "files": indexed}


def search_chunks(query, files, limit=5):
    """BM25-style ranking over indexed chunks, returning only positive matches."""
    query_terms = set(tokenize(query))
    if not query_terms:
        return []
    docs = []
    for source, record in files.items():
        for number, content in enumerate(record.get("chunks", [])):
            terms = tokenize(content)
            if terms:
                docs.append({"source": source, "record": record, "chunk": number, "content": content, "terms": Counter(terms), "length": len(terms)})
    if not docs:
        return []
    n = len(docs)
    average = sum(doc["length"] for doc in docs) / n or 1
    df = Counter(term for doc in docs for term in set(doc["terms"]) if term in query_terms)
    k1, b = 1.5, 0.75
    ranked = []
    for doc in docs:
        score = 0.0
        for term in query_terms:
            frequency = doc["terms"].get(term, 0)
            if frequency:
                inverse = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
                denominator = frequency + k1 * (1 - b + b * doc["length"] / average)
                score += inverse * frequency * (k1 + 1) / denominator
        if score > 0:
            ranked.append({"id": f"doc:{doc['source']}:{doc['chunk']}", "source": doc["source"], "title": Path(doc["source"]).name, "summary": doc["record"].get("summary", ""), "content": doc["content"], "chunk": doc["chunk"], "score": score})
    return sorted(ranked, key=lambda row: (-row["score"], row["source"], row["chunk"]))[:max(1, min(int(limit), 5))]


def knowledge_graph(files, max_file_nodes=60):
    """Return file nodes and links; cluster documents when the folder exceeds 60 files."""
    records = list(files.values())
    groups = []
    if len(records) <= max_file_nodes:
        groups = [[record] for record in records]
    else:
        buckets = defaultdict(list)
        for record in records:
            path = Path(record["path"])
            parent = path.parent.as_posix()
            key = parent if parent != "." else (record.get("keywords") or [path.stem])[0]
            buckets[key].append(record)
        ordered = sorted(buckets.items(), key=lambda item: (-len(item[1]), item[0]))
        if len(ordered) > max_file_nodes:
            top = ordered[:max_file_nodes - 1]
            overflow = [doc for _, docs in ordered[max_file_nodes - 1:] for doc in docs]
            ordered = top + [("Other documents", overflow)]
        groups = [docs for _, docs in ordered]
    nodes = []
    for group in groups:
        first = group[0]
        if len(group) == 1:
            name = Path(first["path"]).name
            node_id = "doc:" + first["path"]
            path = first["path"]
        else:
            parent = Path(first["path"]).parent.as_posix()
            name = parent if parent != "." else (first.get("keywords") or ["Knowledge"])[0]
            node_id = "cluster:" + name
            path = first["path"]
        keywords = Counter(word for record in group for word in record.get("keywords", []))
        nodes.append({
            "id": node_id,
            "name": name,
            "note": first.get("summary", ""),
            "source": "knowledge",
            "path": path,
            "files": [record["path"] for record in group],
            "size": sum(int(record.get("word_count", 0)) for record in group),
            "file_count": len(group),
            "keywords": [word for word, _ in keywords.most_common(24)],
            "modified": max((record.get("mtime", 0) for record in group), default=0),
            "flash": False,
        })
    links = []
    for i, left in enumerate(nodes):
        left_terms = set(left["keywords"])
        for right in nodes[i + 1:]:
            shared = left_terms.intersection(right["keywords"])
            if len(shared) >= 2:
                links.append({"source": left["id"], "target": right["id"], "weight": len(shared), "terms": sorted(shared)[:8]})
    return nodes, sorted(links, key=lambda row: -row["weight"])[:250]


def forget_file(index_file, query):
    files = load_index(index_file)
    normalized = query.strip().casefold()
    matches = [path for path in files if normalized and normalized in path.casefold()]
    for path in matches:
        del files[path]
    if matches:
        _write_index(index_file, files)
    return matches


def recent_files(files, days=7, now=None):
    cutoff = (now if now is not None else datetime.now(timezone.utc).timestamp()) - days * 86400
    return [record for record in files.values() if float(record.get("mtime", 0)) >= cutoff]
