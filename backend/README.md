# Backend

## Run locally

```powershell
Push-Location backend
uv run uvicorn --app-dir src civil_engineering.main:app --reload
Pop-Location
```

## Test

```powershell
Push-Location backend
uv run pytest
Pop-Location
```
