"""
tests/test_rusprofile_api.py — модульные тесты для module2/rusprofile_api.py.

requests.get заменён моком; реальные HTTP-запросы не выполняются.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
import requests

from module2.rusprofile_api import (
    _extract_canonical,
    _fetch_from_rusprofile,
    _normalize_status,
    _parse_date,
    _str_or_none,
    get_entity_by_inn,
)

# ---------------------------------------------------------------------------
# Вспомогательные функции — юнит-тесты
# ---------------------------------------------------------------------------

class TestNormalizeStatus:
    def test_active(self):
        assert _normalize_status("Действующее") == "active"

    def test_liquidated(self):
        assert _normalize_status("Ликвидировано") == "liquidated"
        assert _normalize_status("Исключено из реестра") == "liquidated"
        assert _normalize_status("Недействующее") == "liquidated"

    def test_liquidating(self):
        assert _normalize_status("Ликвидируется") == "liquidating"
        assert _normalize_status("В процессе ликвидации") == "liquidating"
        assert _normalize_status("Ликвидация") == "liquidating"

    def test_reorganizing(self):
        assert _normalize_status("Реорганизация") == "reorganizing"

    def test_unknown(self):
        assert _normalize_status("") == "unknown"
        assert _normalize_status("Неизвестный статус") == "Неизвестный статус"


class TestParseDate:
    def test_ddmmyyyy(self):
        assert _parse_date("20.06.1991") == date(1991, 6, 20)

    def test_yyyymmdd(self):
        assert _parse_date("1991-06-20") == date(1991, 6, 20)

    def test_iso_datetime(self):
        assert _parse_date("2020-01-15T00:00:00") == date(2020, 1, 15)

    def test_empty(self):
        assert _parse_date("") is None
        assert _parse_date("   ") is None

    def test_invalid(self):
        assert _parse_date("not-a-date") is None


class TestStrOrNone:
    def test_normal(self):
        assert _str_or_none("  Москва  ") == "Москва"

    def test_empty(self):
        assert _str_or_none("") is None
        assert _str_or_none("   ") is None
        assert _str_or_none(None) is None


class TestExtractCanonical:
    def test_finds_canonical(self):
        html = '<link rel="canonical" href="https://www.rusprofile.ru/id/123456">'
        assert _extract_canonical(html) == "https://www.rusprofile.ru/id/123456"

    def test_finds_canonical_reversed_attrs(self):
        html = '<link href="https://www.rusprofile.ru/ip/987654" rel="canonical">'
        assert _extract_canonical(html) == "https://www.rusprofile.ru/ip/987654"

    def test_search_url_returns_none(self):
        html = '<link rel="canonical" href="https://www.rusprofile.ru/search?query=1234">'
        assert _extract_canonical(html) is None

    def test_root_url_returns_none(self):
        html = '<link rel="canonical" href="https://www.rusprofile.ru/">'
        assert _extract_canonical(html) is None

    def test_no_canonical_returns_none(self):
        assert _extract_canonical("<html><body>no link here</body></html>") is None


# ---------------------------------------------------------------------------
# Фикстура: кэшированный KV-словарь Сбербанка
# ---------------------------------------------------------------------------

_SBERBANK_KV: dict[str, str] = {
    "orgShortName":    "ПАО СБЕРБАНК",
    "orgFullName":     'ПУБЛИЧНОЕ АКЦИОНЕРНОЕ ОБЩЕСТВО "СБЕРБАНК БАНК РОССИЯ"',
    "orgAddress":      "117997, г Москва, ул Вавилова, д 19",
    "type":            "Организация",
    "commonOGRN":      "1027700132195",
    "commonINN":       "7707083893",
    "commonRegDate":   "20.06.1991",
    "commonBaseFunds": "67760844000",
}


# ---------------------------------------------------------------------------
# get_entity_by_inn — успешные сценарии
# ---------------------------------------------------------------------------

class TestGetEntityByInn:

    @patch("module2.rusprofile_api._fetch_from_rusprofile")
    def test_happy_path_returns_all_fields(self, mock_fetch):
        mock_fetch.return_value = _SBERBANK_KV.copy()
        result = get_entity_by_inn("7707083893")

        assert result["name"] is not None and "СБЕРБАНК" in result["name"].upper()
        assert result["status"]        == "active"
        assert result["reg_date"]      == date(1991, 6, 20)
        assert "Москва" in result["address"]
        assert result["ogrn"]          == "1027700132195"
        assert result["entity_type"]   == "ul"
        assert result["mass_address"]  is False
        assert result["mass_director"] is False
        assert result["capital"] == pytest.approx(67_760_844_000.0)

    @patch("module2.rusprofile_api._fetch_from_rusprofile")
    def test_ip_type_field_sets_entity_type(self, mock_fetch):
        kv = {**_SBERBANK_KV, "type": "Индивидуальный предприниматель"}
        mock_fetch.return_value = kv
        result = get_entity_by_inn("500100732259")
        assert result["entity_type"] == "ip"

    @patch("module2.rusprofile_api._fetch_from_rusprofile")
    def test_ip_inn_length_sets_entity_type(self, mock_fetch):
        kv = {k: v for k, v in _SBERBANK_KV.items() if k != "type"}
        mock_fetch.return_value = kv
        result = get_entity_by_inn("500100732259")
        assert result["entity_type"] == "ip"

    @patch("module2.rusprofile_api._fetch_from_rusprofile")
    def test_liquidating_status(self, mock_fetch):
        kv = {**_SBERBANK_KV, "orgStatus": "Ликвидация"}
        mock_fetch.return_value = kv
        result = get_entity_by_inn("7707083893")
        assert result["status"] == "liquidating"

    @patch("module2.rusprofile_api._fetch_from_rusprofile")
    def test_empty_status_defaults_to_active(self, mock_fetch):
        kv = {k: v for k, v in _SBERBANK_KV.items() if k != "orgStatus"}
        mock_fetch.return_value = kv
        result = get_entity_by_inn("7707083893")
        assert result["status"] == "active"

    @patch("module2.rusprofile_api._fetch_from_rusprofile")
    def test_capital_parsed_as_float(self, mock_fetch):
        kv = {**_SBERBANK_KV, "commonBaseFunds": "10000"}
        mock_fetch.return_value = kv
        result = get_entity_by_inn("7707083893")
        assert result["capital"] == pytest.approx(10_000.0)

    @patch("module2.rusprofile_api._fetch_from_rusprofile")
    def test_no_capital_returns_none(self, mock_fetch):
        kv = {k: v for k, v in _SBERBANK_KV.items() if k != "commonBaseFunds"}
        mock_fetch.return_value = kv
        result = get_entity_by_inn("7707083893")
        assert result["capital"] is None

    @patch("module2.rusprofile_api._fetch_from_rusprofile")
    def test_ogrn_ip_fallback_field(self, mock_fetch):
        kv = {k: v for k, v in _SBERBANK_KV.items() if k != "commonOGRN"}
        kv["commonOGRNIP"] = "312770700000010"
        mock_fetch.return_value = kv
        result = get_entity_by_inn("500100732259")
        assert result["ogrn"] == "312770700000010"

    @patch("module2.rusprofile_api._fetch_from_rusprofile")
    def test_short_name_preferred_over_full(self, mock_fetch):
        mock_fetch.return_value = _SBERBANK_KV.copy()
        result = get_entity_by_inn("7707083893")
        assert result["name"] == "ПАО СБЕРБАНК"

    @patch("module2.rusprofile_api._fetch_from_rusprofile")
    def test_fallback_to_full_name_when_short_absent(self, mock_fetch):
        kv = {k: v for k, v in _SBERBANK_KV.items() if k != "orgShortName"}
        mock_fetch.return_value = kv
        result = get_entity_by_inn("7707083893")
        assert "СБЕРБАНК" in result["name"].upper()

    @patch("module2.rusprofile_api._fetch_from_rusprofile")
    def test_mass_flags_always_false(self, mock_fetch):
        mock_fetch.return_value = _SBERBANK_KV.copy()
        result = get_entity_by_inn("7707083893")
        assert result["mass_address"]  is False
        assert result["mass_director"] is False


# ---------------------------------------------------------------------------
# get_entity_by_inn — обработка ошибок
# ---------------------------------------------------------------------------

class TestGetEntityByInnErrors:

    @patch("module2.rusprofile_api._fetch_from_rusprofile")
    def test_inn_not_found_raises(self, mock_fetch):
        mock_fetch.side_effect = Exception("ИНН 9999999999 не найден на Rusprofile")
        with pytest.raises(Exception, match="не найден"):
            get_entity_by_inn("9999999999")

    @patch("module2.rusprofile_api._fetch_from_rusprofile")
    def test_timeout_exception_propagates(self, mock_fetch):
        mock_fetch.side_effect = Exception("Rusprofile не ответил за 30 секунд")
        with pytest.raises(Exception, match="не ответил"):
            get_entity_by_inn("7707083893")

    @patch("module2.rusprofile_api._fetch_from_rusprofile")
    def test_network_error_propagates(self, mock_fetch):
        mock_fetch.side_effect = Exception("Ошибка сети при обращении к Rusprofile")
        with pytest.raises(Exception, match="Ошибка сети"):
            get_entity_by_inn("7707083893")

    @patch("module2.rusprofile_api._fetch_from_rusprofile")
    def test_http_error_propagates(self, mock_fetch):
        mock_fetch.side_effect = Exception("Ошибка HTTP при обращении к Rusprofile: 503")
        with pytest.raises(Exception, match="Ошибка HTTP"):
            get_entity_by_inn("7707083893")


# ---------------------------------------------------------------------------
# _fetch_from_rusprofile — тесты HTTP-уровня (мок requests.get)
# ---------------------------------------------------------------------------

# Минимальный HTML поиска с canonical URL компании
_SEARCH_HTML = """
<html><head>
<link rel="canonical" href="https://www.rusprofile.ru/id/7707083893">
</head><body>Результаты поиска</body></html>
"""

# Минимальный HTML страницы компании (?print=1)
_COMPANY_HTML = """
<html><body>
<div class="company-name"><span><a href="#">ПАО СБЕРБАНК</a></span></div>
<div class="company-block"><table>
  <tr>
    <td class="dt"><div class="dt-text">ОГРН</div></td>
    <td>1027700132195</td>
  </tr>
  <tr>
    <td class="dt"><div class="dt-text">Статус</div></td>
    <td>Действующее</td>
  </tr>
  <tr>
    <td class="dt"><div class="dt-text">Дата регистрации</div></td>
    <td>20 июня 1991 г.</td>
  </tr>
</table></div>
</body></html>
"""


def _make_response(text: str, status: int = 200) -> MagicMock:
    """Создать мок requests.Response."""
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    resp.raise_for_status = MagicMock()
    if status >= 400:
        http_err = requests.HTTPError(response=MagicMock(status_code=status))
        resp.raise_for_status.side_effect = http_err
    return resp


class TestFetchFromRusprofile:

    def test_timeout_on_search_raises(self):
        with patch("module2.rusprofile_api.requests.get",
                   side_effect=requests.Timeout()):
            with pytest.raises(Exception, match="не ответил"):
                _fetch_from_rusprofile("7707083893")

    def test_http_error_on_search_raises(self):
        err_resp = _make_response("", status=503)
        with patch("module2.rusprofile_api.requests.get", return_value=err_resp):
            with pytest.raises(Exception, match="Ошибка HTTP"):
                _fetch_from_rusprofile("7707083893")

    def test_inn_not_found_when_no_canonical(self):
        """Если поиск не вернул canonical URL компании — ИНН не найден."""
        search_resp = _make_response(
            '<link rel="canonical" href="https://www.rusprofile.ru/search?query=1234567890">'
        )
        with patch("module2.rusprofile_api.requests.get", return_value=search_resp):
            with pytest.raises(Exception, match="не найден"):
                _fetch_from_rusprofile("1234567890")

    def test_timeout_on_company_page_raises(self):
        """Первый запрос успешен, второй — таймаут."""
        search_resp = _make_response(_SEARCH_HTML)
        with patch("module2.rusprofile_api.requests.get",
                   side_effect=[search_resp, requests.Timeout()]):
            with pytest.raises(Exception, match="не ответил"):
                _fetch_from_rusprofile("7707083893")

    def test_success_returns_parsed_kv(self):
        """Оба запроса успешны — возвращает разобранный словарь."""
        search_resp  = _make_response(_SEARCH_HTML)
        company_resp = _make_response(_COMPANY_HTML)
        with patch("module2.rusprofile_api.requests.get",
                   side_effect=[search_resp, company_resp]):
            result = _fetch_from_rusprofile("7707083893")

        assert result["orgShortName"] == "ПАО СБЕРБАНК"
        assert result["commonOGRN"]   == "1027700132195"
        assert result["commonRegDate"] == "20.06.1991"

    def test_empty_page_after_fetch_raises(self):
        """Страница скачалась, но данные не распознаны."""
        search_resp  = _make_response(_SEARCH_HTML)
        company_resp = _make_response("<html><body>пустая страница</body></html>")
        with patch("module2.rusprofile_api.requests.get",
                   side_effect=[search_resp, company_resp]):
            with pytest.raises(Exception, match="не найден"):
                _fetch_from_rusprofile("7707083893")

    def test_network_error_raises(self):
        with patch("module2.rusprofile_api.requests.get",
                   side_effect=requests.ConnectionError("nxdomain")):
            with pytest.raises(Exception, match="Ошибка сети"):
                _fetch_from_rusprofile("7707083893")
