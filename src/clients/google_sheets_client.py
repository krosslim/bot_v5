"""Google Sheets API v4 через сервисный аккаунт. Синхронный клиент: из async-кода вызывать через asyncio.to_thread.

GOOGLE_SHEET_CREDENTIALS — содержимое JSON-ключа сервисного аккаунта (одной строкой),
GOOGLE_SHEET_KEY — id таблицы (из ссылки .../spreadsheets/d/<id>/edit). Сервисному аккаунту нужен доступ
редактора к таблице.
"""
import json
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

import google_auth_httplib2
import httplib2
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
TIMEOUT_SEC = 30


class GoogleSheetsError(Exception):
    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class SheetInfo:
    sheet_id: int
    title: str
    metadata: Dict[str, str]     # developer metadata листа: ключ → значение


class GoogleSheetsClient:
    def __init__(self, credentials_json: str, spreadsheet_id: str):
        try:
            info = json.loads(credentials_json)
        except json.JSONDecodeError as e:
            raise GoogleSheetsError(f"GOOGLE_SHEET_CREDENTIALS не JSON: {e.msg}") from None
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        http = google_auth_httplib2.AuthorizedHttp(creds, http=httplib2.Http(timeout=TIMEOUT_SEC))
        # Описание API берётся из пакета (static discovery), сети для build() не нужно
        self._sheets = build("sheets", "v4", http=http, cache_discovery=False).spreadsheets()
        self.spreadsheet_id = spreadsheet_id

    def _run(self, request):
        try:
            return request.execute(num_retries=2)
        except HttpError as e:
            raise GoogleSheetsError(f"Google Sheets API {e.status_code}: {e.reason}", e.status_code) from e
        except (OSError, httplib2.HttpLib2Error) as e:
            raise GoogleSheetsError(f"Google Sheets недоступен: {e}") from e

    def sheets(self) -> List[SheetInfo]:
        res = self._run(self._sheets.get(
            spreadsheetId=self.spreadsheet_id,
            fields="sheets(properties(sheetId,title),developerMetadata(metadataKey,metadataValue))",
        ))
        return [
            SheetInfo(
                sheet_id=s["properties"]["sheetId"],
                title=s["properties"]["title"],
                metadata={m["metadataKey"]: m.get("metadataValue", "") for m in s.get("developerMetadata", [])},
            )
            for s in res.get("sheets", [])
        ]

    def batch_update(self, requests: Sequence[dict]) -> dict:
        return self._run(self._sheets.batchUpdate(spreadsheetId=self.spreadsheet_id,
                                                  body={"requests": list(requests)}))

    def write_values(self, data: Sequence[dict]) -> dict:
        return self._run(self._sheets.values().batchUpdate(
            spreadsheetId=self.spreadsheet_id,
            body={"valueInputOption": "USER_ENTERED", "data": list(data)},
        ))

    def read_values(self, a1_range: str, formulas: bool = False) -> List[List[str]]:
        res = self._run(self._sheets.values().get(
            spreadsheetId=self.spreadsheet_id, range=a1_range,
            valueRenderOption="FORMULA" if formulas else "FORMATTED_VALUE",
        ))
        return res.get("values", [])
