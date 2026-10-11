"""Tests for folioman_client.core.cas_reader — unified CAS PDF reader and dispatch."""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest
from casparser.exceptions import IncorrectPasswordError, ParserException
from casparser.types import CASData, NSDLCASData
from folioman_client.core.cas_reader import ParsedCas, read_cas
from folioman_client.core.models.cas import (
    CasInvestorIdentity,
    EcasStatement,
    MfCasStatement,
)
from folioman_client.core.parser import CASParseError, CASPasswordError


def test_parsed_cas_defaults_and_properties():
    parsed = ParsedCas()
    assert parsed.mf is None
    assert parsed.ecas is None
    assert isinstance(parsed.investor, CasInvestorIdentity)
    assert parsed.is_ecas is False

    mock_ecas = MagicMock(spec=EcasStatement)
    parsed_ecas = ParsedCas(ecas=mock_ecas)
    assert parsed_ecas.is_ecas is True


def test_read_cas_mf_success():
    mock_data = MagicMock(spec=CASData)
    mock_mf = MagicMock(spec=MfCasStatement)
    mock_identity = CasInvestorIdentity(name="John Doe", pan="ABCDE1234F")

    with (
        patch("casparser.read_cas_pdf", return_value=mock_data) as mock_pdf,
        patch(
            "folioman_client.core.cas_reader.map_cas_data", return_value=mock_mf
        ) as mock_map,
        patch(
            "folioman_client.core.cas_reader.mf_investor_identity",
            return_value=mock_identity,
        ) as mock_id,
    ):
        file_obj = io.BytesIO(b"%PDF-test")
        result = read_cas(file_obj, "secret123")

        mock_pdf.assert_called_once_with(file_obj, "secret123", output="dict")
        mock_map.assert_called_once_with(mock_data)
        mock_id.assert_called_once_with(mock_data)
        assert result.mf is mock_mf
        assert result.ecas is None
        assert result.investor == mock_identity
        assert result.is_ecas is False


def test_read_cas_ecas_success():
    mock_data = MagicMock(spec=NSDLCASData)
    mock_ecas = MagicMock(spec=EcasStatement)
    mock_identity = CasInvestorIdentity(name="Jane Doe", pan="XYZPK9876L")

    with (
        patch("casparser.read_cas_pdf", return_value=mock_data) as mock_pdf,
        patch(
            "folioman_client.core.cas_reader.map_ecas_data", return_value=mock_ecas
        ) as mock_map,
        patch(
            "folioman_client.core.cas_reader.ecas_investor_identity",
            return_value=mock_identity,
        ) as mock_id,
    ):
        result = read_cas("statement.pdf", "secret456")

        mock_pdf.assert_called_once_with("statement.pdf", "secret456", output="dict")
        mock_map.assert_called_once_with(mock_data)
        mock_id.assert_called_once_with(mock_data)
        assert result.ecas is mock_ecas
        assert result.mf is None
        assert result.investor == mock_identity
        assert result.is_ecas is True


def test_read_cas_incorrect_password():
    with (
        patch(
            "casparser.read_cas_pdf", side_effect=IncorrectPasswordError("Bad password")
        ),
        pytest.raises(CASPasswordError, match="Bad password"),
    ):
        read_cas("statement.pdf", "wrong")


def test_read_cas_parser_exception():
    with (
        patch(
            "casparser.read_cas_pdf", side_effect=ParserException("Corrupted document")
        ),
        pytest.raises(CASParseError, match="Corrupted document"),
    ):
        read_cas("corrupt.pdf", "secret")


def test_read_cas_unsupported_file_type():
    dummy = MagicMock()
    dummy.file_type = "UNRECOGNIZED"
    with (
        patch("casparser.read_cas_pdf", return_value=dummy),
        pytest.raises(CASParseError, match="unsupported CAS file_type 'UNRECOGNIZED'"),
    ):
        read_cas("statement.pdf", "secret")


def test_read_cas_unsupported_object_without_file_type():
    dummy = object()
    with (
        patch("casparser.read_cas_pdf", return_value=dummy),
        pytest.raises(CASParseError, match=r"unsupported CAS file_type '\?'"),
    ):
        read_cas("statement.pdf", "secret")
