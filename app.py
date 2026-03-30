"""
Local development entry point.

    pip install -r requirements.txt
    uvicorn app:app --reload

Then open http://localhost:8000

For Vercel deployment the entry point is api/index.py (see vercel.json).
"""

from api.index import app  # noqa: F401  re-export for uvicorn

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
