from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path

from ingestion.bafin import _party_detail_links, _search_rows as bafin_search_rows
from ingestion.newsweb import NewsWebAdapter
from ingestion.sweden_fi import SwedenFiAdapter, _search_rows
from parsers.newsweb_json import _afm_form, _body_embedded_form, _compact_english_form, _english_krt_form, _krt_form, _schouw_forms, _thor_forms
from parsers.bafin_html import parse as parse_bafin
from parsers.sweden_fi_html import parse as parse_sweden
from parsers.six_json import parse as parse_six
from parsers.amf_pdf import _parse_text as parse_amf_text
from ingestion.unternehmensregister import _job_number as ureg_job_number, _search_rows as ureg_search_rows
from parsers.unternehmensregister_html import parse as parse_ureg
from ingestion.nl_afm import _xml_records as nl_afm_xml_records
from parsers.nl_afm_html import parse as parse_nl_afm
from parsers.denmark_oam_json import _fallback_danish as parse_danish_fallback, _fallback_form as parse_denmark_english_fallback


class AdapterContractTest(unittest.TestCase):
    def test_sweden_zero_result_page_does_not_require_detail_links(self):
        page = '''<html><label>Transaktionsdatum</label><span class="badge badge-info">0</span></html>'''
        self.assertEqual(_search_rows(page.encode()), (0, []))

    def test_sweden_discovery_partitions_each_publication_date(self):
        adapter = SwedenFiAdapter(request_delay=0)
        calls = []

        def page(interval_from, interval_to, page):
            calls.append((interval_from, interval_to, page))
            report = f"A{interval_from[-2:]}-1"
            return 1, [{"report_version": report, "href": f"/Index/{report}", "published_date": interval_from}]

        adapter._page = page
        records = adapter.discover("2026-09-07", "2026-09-09", None)
        self.assertEqual(calls, [("2026-09-07", "2026-09-07", 1), ("2026-09-08", "2026-09-08", 1), ("2026-09-09", "2026-09-09", 1)])
        self.assertEqual([record.native_record_id for record in records], ["A07-1", "A08-1", "A09-1"])

    def test_denmark_oam_english_pca_form(self):
        text = '''Details of the person discharging managerial responsibilities/person closely associated
        a) Name A/S Motortramp 2. Reason for the notification a) Position /status A/S Motortramp is closely related; CEO and board member, Johanne Riegels, is also a board member
        b) Initial notification Initial notification 3. Details of the issuer a) Name NORDEN A/S b) LEI 529900RGXD3CBR3BRU63
        4. Details of the transaction(s) a) Description of the financial instrument Identification code Shares DK0060083210
        b) Nature of the transaction Sale c) Price(s) and volume(s) Price(s) Volume(s) DKK 382.17 1,787
        d) Aggregated information 1,787 DKK 682,937.79 64 Date of the transaction 2026-09-07
        f) Place of the transaction Nasdaq Copenhagen (XCSE)'''
        filing = parse_denmark_english_fallback({"messageId": "1"}, text, "NORDEN A/S", "529900RGXD3CBR3BRU63", "A/S Motortramp")
        group = filing["transaction_groups"][0]
        self.assertEqual(filing["transacting_party"]["pdmr_or_pca"], "pca")
        self.assertEqual((group["action"], group["rows"][0]["price_amount_reported"], group["rows"][0]["quantity"]), ("disposal", "382.17", "1787"))

    def test_denmark_oam_danish_aggregate_form(self):
        text = '''Skema, hvori transaktioner udført af personer med ledelsesansvar skal indberettes
        1. Nærmere oplysninger om personen med ledelsesansvar a) Navn Færch B Holding ApS ejet af direktør Jakob Bendtsen
        2. Årsag til indberetningen a) Stilling/titel Administrerende Direktør b) Første indberetning/ændring Første indberetning
        3. Nærmere oplysninger om udstederen a) Navn Strategic Partners A/S b) LEI-kode 54930025OZD2GGSQ7L42
        4. Nærmere oplysninger om transaktionen a) Beskrivelse Identifikationskode DK0062502894 b) Transaktionens art køb
        d) Aggregerede oplysninger - Aggregeret mængde - Pris 451 stk. 303.135 DKK
        e) Dato for transaktionen 03-09-2026 f) Sted for transaktionen XCSE'''
        filing = parse_danish_fallback({"messageId": "2"}, text, "Færch B Holding ApS")
        row = filing["transaction_groups"][0]["rows"][0]
        self.assertEqual((filing["notification_status"], filing["transacting_party"]["pdmr_or_pca"]), ("initial", "pca"))
        self.assertEqual((row["quantity"], row["consideration_reported"], row["consideration_currency"]), ("451", "303135", "DKK"))

    def test_nl_afm_xml_discovery_preserves_pca_metadata(self):
        body = b'''<register name="transacties-leidinggevenden-mar19-"><vermelding>
        <meldingid>202609017BF4AE18-D44E-4004-B3F8-336C5C452671</meldingid><transactiedatum>9/1/2026 12:00:00 AM</transactiedatum>
        <uitgevendeinstelling>Van Lanschot Kempen N.V.</uitgevendeinstelling><meldingsplichtige>MVDP N.V.</meldingsplichtige>
        <nauwgelieerdaan>Vanderlinden T.G.P.M.</nauwgelieerdaan></vermelding></register>'''
        records = nl_afm_xml_records(body)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].native_record_id, "202609017BF4AE18-D44E-4004-B3F8-336C5C452671")
        self.assertEqual(records[0].metadata["transaction_date"], "2026-09-01")
        self.assertEqual(records[0].metadata["related_pdmr_name"], "Vanderlinden T.G.P.M.")

    def test_nl_afm_detail_retains_fills_and_aggregate(self):
        page = b'''<html><body>
        <span class="cc-em--detail-list__label">Notifiable</span><span class="cc-em--detail-list__value"><span>MVDP N.V.</span></span>
        <span class="cc-em--detail-list__label">Issuing institution</span><span class="cc-em--detail-list__value"><span>Van Lanschot Kempen N.V.</span></span>
        <span class="cc-em--detail-list__label">LEI</span><span class="cc-em--detail-list__value"><span>724500D8WOYCL1BUCB80</span></span>
        <span class="cc-em--detail-list__label">Position/Status</span><span class="cc-em--detail-list__value"><span>Member Management Board</span></span>
        <span class="cc-em--detail-list__label">Transaction</span><span class="cc-em--detail-list__value"><span>01 sep 2026</span></span>
        <h2>Transactions</h2><table><tbody><tr>
        <td><span class="cc-mobile-title">Instrument type</span>Gewoon aandeel</td><td><span class="cc-mobile-title">ISIN</span>NL00150001Q9</td>
        <td>Verwerving</td><td>Overdracht</td><td>Nee</td><td>EURONEXT - EURONEXT AMSTERDAM</td><td>10,25</td><td>2.000,00</td><td>EUR</td>
        </tr><tr>
        <td>Gewoon aandeel</td><td>NL00150001Q9</td><td>Verwerving</td><td>Overdracht</td><td>Nee</td><td>EURONEXT - EURONEXT AMSTERDAM</td><td>11,00</td><td>1.000,00</td><td>EUR</td>
        </tr></tbody></table>
        <h2>Aggregated information</h2><table><tbody><tr>
        <td>Gewoon aandeel</td><td>NL00150001Q9</td><td>Verwerving</td><td>Overdracht</td><td>EURONEXT - EURONEXT AMSTERDAM</td><td>10,50</td><td>3.000,00</td><td>EUR</td>
        </tr></tbody></table></body></html>'''
        payload = parse_nl_afm(page, {"native_record_id": "sample", "url": "https://example.test", "transaction_date": "2026-09-01", "related_pdmr_name": "Vanderlinden T.G.P.M."})
        filing = payload["filings"][0]
        group = filing["transaction_groups"][0]
        self.assertEqual(len(filing["transaction_groups"]), 1)
        self.assertEqual((filing["transacting_party"]["pdmr_or_pca"], filing["transacting_party"]["party_type"]), ("pca", "legal_entity"))
        self.assertEqual((group["action"], group["venue_mic"]), ("acquisition", "XAMS"))
        self.assertEqual([row["representation"] for row in group["rows"]], ["individual", "individual", "aggregate"])
        self.assertEqual((group["rows"][0]["price_amount_reported"], group["rows"][0]["quantity"]), ("10.25", "2000.00"))

    def test_nl_afm_aggregates_do_not_merge_distinct_transaction_types(self):
        fields = '''<span class="cc-em--detail-list__label">Notifiable</span><span class="cc-em--detail-list__value"><span>Jane Doe</span></span>
        <span class="cc-em--detail-list__label">Issuing institution</span><span class="cc-em--detail-list__value"><span>Aegon Ltd.</span></span>
        <span class="cc-em--detail-list__label">Position/Status</span><span class="cc-em--detail-list__value"><span>Board member</span></span>
        <span class="cc-em--detail-list__label">Transaction</span><span class="cc-em--detail-list__value"><span>27 aug 2026</span></span>'''
        detail_rows = '''<tr><td>Conditional share award</td><td></td><td>Verwerving</td><td>Dividend</td><td>Nee</td><td>OTC</td><td>0,00</td><td>9.294,00</td><td>EUR</td></tr>
        <tr><td>Conditional share award</td><td></td><td>Verwerving</td><td>voorwaardelijke toekenning</td><td>Nee</td><td>OTC</td><td>0,00</td><td>322.872,00</td><td>EUR</td></tr>'''
        aggregate_rows = '''<tr><td>Conditional share award</td><td></td><td>Verwerving</td><td>Dividend</td><td>OTC</td><td>0,00</td><td>9.294,00</td><td>EUR</td></tr>
        <tr><td>Conditional share award</td><td></td><td>Verwerving</td><td>voorwaardelijke toekenning</td><td>OTC</td><td>0,00</td><td>322.872,00</td><td>EUR</td></tr>'''
        page = f'''<html>{fields}<h2>Transactions</h2><table><tbody>{detail_rows}</tbody></table>
        <h2>Aggregated information</h2><table><tbody>{aggregate_rows}</tbody></table></html>'''.encode()
        filing = parse_nl_afm(page, {"native_record_id": "sample", "url": "https://example.test", "transaction_date": "2026-08-27"})["filings"][0]
        self.assertEqual(len(filing["transaction_groups"]), 2)
        self.assertEqual([[row["quantity"] for row in group["rows"]] for group in filing["transaction_groups"]], [["9294.00", "9294.00"], ["322872.00", "322872.00"]])

    def test_unternehmensregister_search_filters_explicit_pdmr_titles(self):
        page = '''<html>Suchergebnis publicationCategory<table><tr><td><a data-testid="normal-pub" href="/de/publication?payload=abc123">Meldung von Personen, die Führungsaufgaben wahrnehmen</a> Datum: 19.12.2016</td></tr><tr><td><a data-testid="normal-pub" href="/de/publication?payload=other">Jahresabschluss</a> Datum: 19.12.2016</td></tr></table><a href="/de/suche?from=30">2</a></html>'''
        records, offsets = ureg_search_rows(page.encode())
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].metadata["published_date"], "2016-12-19")
        self.assertEqual(offsets, {30})

    def test_unternehmensregister_uses_stable_job_number(self):
        self.assertEqual(ureg_job_number(b'<script>{\\"jobNumber\\":\\"161274002316\\"}</script>'), "161274002316")

    def test_unternehmensregister_numbered_english_template(self):
        page = b'''<html><body>
        1. Details of the person discharging managerial responsibilities / person closely associated
        First name: Davin Last name(s): Lee
        2. Reason for the notification a) Position / status Position: Member of the management team
        b) Initial notification
        3. Details of the issuer, emission allowance market participant a) Name Dialog Semiconductor Plc. b) LEI 529900QA2LORU6646N15
        4. Details of the transaction(s) a) Description of the financial instrument, type of instrument, identification code Type: Share ISIN: GB0059822006
        b) Nature of the transaction Sale of shares c) Price(s) and volume(s)
        d) Aggregated information Price Aggregated volume 38.23 EUR 1,500 EUR
        e) Date of the transaction 2016-12-16 f) Place of the transaction Name: XETRA MIC: XTRA
        19.12.2016 The DGAP Distribution Services include Regulatory Announcements
        </body></html>'''
        filing = parse_ureg(page, {"native_record_id": "sample", "url": "https://example.test", "published_date": "2016-12-19"})["filings"][0]
        group = filing["transaction_groups"][0]
        self.assertEqual(filing["transacting_party"]["name_raw"], "Davin Lee")
        self.assertEqual((group["action"], group["trade_date"], group["venue_raw"]), ("disposal", "2016-12-16", "Name: XETRA MIC: XTRA"))
        self.assertIsNone(group["rows"][0]["quantity"])

    def test_unternehmensregister_verkauf_is_disposal(self):
        page = b'''<html><body>
        Angaben zu den Personen Name: Max Mustermann Grund der Meldung Position/Status: Vorstand b) Erstmeldung/Berichtigung: Erstmeldung
        Angaben zum Emittenten Name: Beispiel AG LEI: 529900QA2LORU6646N15 Angaben zum Gesch\xc3\xa4ft
        a) Art des Instruments: Aktie Kennung: DE0001234567 b) Art des Gesch\xc3\xa4fts: Verkauf c) Preis
        d) Aggregierte Informationen Aggregiertes Volumen: 100 EUR Preis: 1000 EUR e) Datum des Gesch\xc3\xa4fts: 16.12.2016
        f) Ort des Gesch\xc3\xa4fts: XETRA Weitere Angaben
        </body></html>'''
        filing = parse_ureg(page, {"native_record_id": "sample-de", "url": "https://example.test"})["filings"][0]
        self.assertEqual(filing["transaction_groups"][0]["action"], "disposal")

    def test_amf_pdf_text_retains_detail_and_aggregate_rows(self):
        text = '''2026DD1137000 Individual notification NAME / POSITION - STATUS OF THE PERSON DISCHARGING MANAGERIAL RESPONSABILITIES / PERSON CLOSELY ASSOCIATED: GEST INVEST legal person closely associated with Philippe ROSIO INITIAL NOTIFICATION / AMENDMENT: Initial notification DETAILS OF THE ISSUER NAME : FONCIERE INEA LEI : 9695000H29HRRE478062 DETAIL OF THE TRANSACTION 1 DATE OF THE TRANSACTION : 04 September 2026 PLACE OF THE TRANSACTION : Euronext Paris NATURE OF THE TRANSACTION : Acquisition DESCRIPTION OF THE FINANCIAL INSTRUMENT, TYPE OF INSTRUMENT : Share IDENTIFICATION CODE : FR0010341032 DETAILED OPERATION INFORMATION PRICE : 32.3700 Euro VOLUME : 232.0000 AGGREGATED INFORMATION PRICE : 32.3700 Euro AGGREGATED VOLUME : 232.0000 DATE OF RECEIPT OF THE NOTIFICATION : 08 September 2026'''
        filing = parse_amf_text(text)["filings"][0]
        group = filing["transaction_groups"][0]
        self.assertEqual((filing["issuer"]["lei_raw"], filing["transacting_party"]["pdmr_or_pca"]), ("9695000H29HRRE478062", "pca"))
        self.assertEqual((group["trade_date"], group["venue_mic"], group["instrument"]["isin_raw"]), ("2026-09-04", "XPAR", "FR0010341032"))
        self.assertEqual([row["representation"] for row in group["rows"]], ["individual", "aggregate"])

    def test_amf_comments_can_identify_aggregate_and_effective_acquisition(self):
        text = '''2026DD1137001 Individual notification NAME / POSITION - STATUS OF THE PERSON DISCHARGING MANAGERIAL RESPONSABILITIES / PERSON CLOSELY ASSOCIATED: EXAMPLE SAS legal person closely associated with Jane Doe INITIAL NOTIFICATION / AMENDMENT: Initial notification DETAILS OF THE ISSUER NAME : EXAMPLE SA LEI : 9695000H29HRRE478062 DETAIL OF THE TRANSACTION DATE OF THE TRANSACTION : 02 September 2026 PLACE OF THE TRANSACTION : Outside a trading venue NATURE OF THE TRANSACTION : Dénouement d’un contrat financier dérivé DESCRIPTION OF THE FINANCIAL INSTRUMENT, TYPE OF INSTRUMENT : Share IDENTIFICATION CODE : FR0010341032 DETAILED OPERATION INFORMATION PRICE : 1.7500 Euro VOLUME : 1 962.0000 AGGREGATED INFORMATION PRICE : 1.7500 Euro AGGREGATED VOLUME : 1 962.0000 DATE OF RECEIPT OF THE NOTIFICATION : 07 September 2026 COMMENTS : Les informations correspondent à un prix et à un volume agrégé. Ces dénouements correspondent à des acquisitions effectives d’actions.'''
        group = parse_amf_text(text)["filings"][0]["transaction_groups"][0]
        self.assertEqual(group["action"], "acquisition")
        self.assertEqual([row["representation"] for row in group["rows"]], ["aggregate"])

    def test_six_detail_preserves_anonymity_and_reported_amounts(self):
        payload = parse_six(b'''{"status":"Ok","totalCount":1,"itemList":[{"correctorId":"","obligorRelatedPartyInd":"I","transactionSize":14.0,"transactionAmountPerSecurityCHF":144.0,"obligorFunctionCode":"1","transactionAmountCHF":2016.0,"swxListed":"T","notificationSubmitter":"Investis Holding SA","ISIN":"CH0325094297","transactionConditions":"","transactionDate":20260907,"correcteeId":"","notificationSubmitterId":"INVESH","notificationId":"T1Q9700063","buySellIndicator":"1","securityTypeCode":"7","securityDescription":""}]}''')
        filing = payload["filings"][0]
        group = filing["transaction_groups"][0]
        self.assertEqual(filing["transacting_party"]["party_type"], "anonymous_role")
        self.assertEqual(filing["transacting_party"]["pdmr_or_pca"], "pca")
        self.assertEqual((group["action"], group["trade_date"], group["venue_mic"]), ("acquisition", "2026-09-07", "XSWX"))
        self.assertEqual((group["rows"][0]["quantity"], group["rows"][0]["consideration_reported"]), ("14.0", "2016.0"))

    def test_compact_newsweb_form_inherits_transaction_currency(self):
        text = """1 Details of the primary insider / person closely associated
        a) Name Kona BidCo AS
        2 Reason for the notification
        a) Position/status Closely associated with Fredrik Raaum, Chair of the Board
        b) Initial notification Initial notification
        3 Details of the issuer
        a) Name Zalaris ASA
        b) LEI 549300XBITM62HH7HW18
        4.1 Details of the transaction(s)
        a) Description of the financial instrument Ordinary shares ISIN: NO0010708910
        b) Nature of the transaction Purchase
        c) Price(s) and volume(s) Price(s) in NOK Volume(s) 100 5
        d) Aggregated information 5 500
        e) Date of the transaction 2026-09-01
        f) Place of the transaction Oslo Bors (XOSL)"""
        filing = _compact_english_form({"messageId": 681422, "body": ""}, text)
        self.assertIsNotNone(filing)
        group = filing["transaction_groups"][0]
        self.assertEqual((group["action"], group["rows"][0]["price_currency_normalized"]), ("acquisition", "NOK"))
        self.assertEqual(group["instrument"]["isin_raw"], "NO0010708910")

    def test_compact_form_accepts_pdf_labels_without_spaces(self):
        text = """1Details of the person discharging managerial responsibilities/person closely associated
        a)Name Helge Hoff Hansen 2Reason for the notification a)Position/status Primary insider, Chief Operations Officer
        b)Initial notification/ Amendment Initial notification 3Details of issuer a)Name Pexip Holding ASA
        b)LEI 549300S79JFZK79XBI07 4Details of the transaction(s)
        Description of the financial instrument, type of instrument Identification code Shares in Pexip Holding ASA (ISIN: NO0010840507)
        b)Nature of the transaction Sale of shares c)Price(s) and volume(s) Price(s) Volume(s) NOK 74.4 4,048 shares
        d)Aggregated information Aggregated volume 4,048 shares Aggregated price NOK 301,171.2
        e)Date of the transaction 2026-09-08 f)Place of the transaction MIC: XOSL Pexip | Public | Anyone"""
        filing = _compact_english_form({"messageId": 681853, "body": ""}, text)
        self.assertIsNotNone(filing)
        group = filing["transaction_groups"][0]
        self.assertEqual((group["action"], group["trade_date"], group["instrument"]["isin_raw"]), ("disposal", "2026-09-08", "NO0010840507"))
        self.assertEqual((group["rows"][0]["price_amount_reported"], group["rows"][0]["quantity"]), ("74.4", "4048"))
        self.assertEqual((group["venue_raw"], group["rows"][0]["representation"]), ("MIC: XOSL", "individual"))

    def test_compact_option_form_does_not_assign_underlying_isin(self):
        text = """1 Details of the Primary Insider/Related Party a) Name Timothy Herpin
        2 Reason for the notification a) Position/status Chief Business Officer b) Initial notification Initial
        3 Details of the company a) Name Lytix Biopharma ASA b) LEI 549300NXMIMRSBCDZO71
        4 Details of the transaction(s) a) Description of the financial instrument Shares Options related to shares with ISIN NO0010405780
        b) Nature of the transaction Grant of share options c) Price(s) and volume(s) Price(s) Volume(s) 0 384,500
        d) Aggregated information total consideration of NOK 0 e) Date of the transaction 2026-09-03
        f) Place of transaction XOFF - Outside a trading venue"""
        filing = _compact_english_form({"messageId": 681627, "body": ""}, text)
        instrument = filing["transaction_groups"][0]["instrument"]
        self.assertEqual(instrument["instrument_type"], "option")
        self.assertNotIn("isin_raw", instrument)
        self.assertEqual(instrument["underlying_isin_raw"], "NO0010405780")
        self.assertIn("reported_isin_identifies_underlying_share_not_option", filing["quality_issues"])

    def test_body_embedded_newsweb_form(self):
        body = """Details in accordance with Article 19(6)
        1. Details of the person discharging managerial responsibilities/person closely associated
        a) Name: Bel-Mar Holding AS b) Position/status: Person closely associated with Piotr C. Wingaard, Chief Commercial Officer of Grieg Seafood ASA c) Initial notification/amendment: Initial
        2. Reason for the notification Initial
        3. Details of the issuer a) Name: Grieg Seafood ASA b) LEI: 5967007LIEEXZXH5VC37
        4. Details of the transaction a) Description of the financial instrument, type of instrument, identification code: Shares, ISIN NO0010365521
        b) Nature of the transaction: Acquisition c) Price(s) and volume(s): NOK 28.3746 per share; 9,000 shares
        d) Date of the transaction: 3 September 2026 e) Place of the transaction: Oslo Stock Exchange (Oslo Bors)
        This information is subject to disclosure requirements"""
        filing = _body_embedded_form({"messageId": 681701, "body": body, "issuerName": "Grieg Seafood ASA"})
        group = filing["transaction_groups"][0]
        self.assertEqual((group["trade_date"], group["rows"][0]["quantity"]), ("2026-09-03", "9000"))

    def test_english_krt_slash_date_requires_corroboration(self):
        text = """KRT-1500 Form for notification
        Date sent: 03.09.2026 / 14:00
        Reference number: abc123
        1.3.1 I report as / on behalf of:
        An entity closely associated with a primary insider
        1.6.2 Company name (for the closely associated legal person)
        ML KAPITAL AS
        1.7.1 Name
        Martin Lundberg
        1.7.2 Position/Role
        CFO
        2.2.1 LEI code (for issuer or emission allowance market participant)
        213800GIV9N2A714T434
        2.2.2 Company name (for issuer or emission allowance market participant)
        DOF Group ASA
        2.3.1 Instrument : Share
        2.3.2 ISIN code : NO0012851874
        2.4.1 Transaction type : Sale
        2.6.1 Currency : NOK
        2.8.1 Average price per unit : 132
        2.8.2 Aggregated volume : 25 000
        2.9.1 Specify date : 09/03/2026
        2.10.1 Trading venue : XOSL - Oslo Bors"""
        filing = _english_krt_form({"messageId": 1, "issuerName": "DOF Group ASA", "body": "Sold on 3 September 2026"}, text)
        self.assertEqual(filing["native_notification_reference"], "abc123")
        self.assertEqual(filing["transaction_groups"][0]["trade_date"], "2026-09-03")
        with self.assertRaises(Exception):
            _english_krt_form({"messageId": 1, "issuerName": "DOF Group ASA", "body": ""}, text.replace("03.09.2026", "04.09.2026"))

    def test_afm_form_preserves_fills_and_unselected_aggregate(self):
        text = """AFM notification form MAR 19 - managers transactions
        if applicable. Stefan H.A. Meichsner 2. Reason for the notification
        e.g. CEO, CFO. Chief Financial Officer b) Initial notification
        Full name of the entity MPC Energy Solutions NV b) LEI
        ISO 17442 LEI code. 724500EBN1V9P4WME110
        1. NL0015268814 2. NL0015268814
1 NOK 2.23 17,000
2 NOK 2.22 20,000
        37,000 NOK 2.22
1. 2026-09-02
2. 2026-09-02
1. Euronext Growth Oslo
2. Euronext Growth Oslo"""
        filing = _afm_form({"messageId": 681451}, text)
        rows = filing["transaction_groups"][0]["rows"]
        self.assertEqual([row["representation"] for row in rows], ["individual", "individual", "aggregate"])
        self.assertEqual([row["quantity"] for row in rows], ["17000", "20000", "37000"])

    def test_schouw_repeated_forms_remain_separate_actions(self):
        template = """1. Details of the person discharging managerial responsibilities
        a) Name Jens Bjerg Sorensen 2. Reason for the notification a) Position/status Executive management b) Initial notification Second
        3. Details of the issuer a) Name AKTIESELSKABET SCHOUW & CO. b) LEI 213800V2R9WMMZASKK57
        4. Details of the transaction(s) a) Description Shares DK0010253921 b) Nature of the transaction {nature}
        c) Price(s) and volume(s) Price(s) Volume(s) DKK {price} 25,000 shares d) Aggregated information
        e) Date of the transaction 2 September 2026 f) Place of transaction Outside a trading venue"""
        text = "Aktieselskabet Schouw & Co.\n" + template.format(nature="Exercise of options", price="571.89").replace("Outside a trading venue", "Outside a trading venue 2/2") + "\n" + template.format(nature="Sale of shares in connection with exercise of options", price="780.00")
        filing = _schouw_forms({"messageId": 681625, "body": ""}, text)
        self.assertEqual([group["action"] for group in filing["transaction_groups"]], ["exercise", "disposal"])
        self.assertEqual(filing["transaction_groups"][0]["venue_raw"], "Outside a trading venue")

    def test_thor_share_lending_is_not_a_purchase_or_disposal(self):
        template = """NOTIFICATION OF TRANSACTIONS PURSUANT TO THE MARKET ABUSE REGULATION ARTICLE 19
        1 Details a) Name Scatec Innovation AS 2 Reason a) Position/status A close associate of John Andersen, chair of the board b) Initial notification
        3 Details of the issuer a) Name THOR MEDICAL ASA b) LEI 5967007LIEEXZXG6DK30
        4 Details a) Description Shares NO0010597883 b) Nature of the transaction {nature}
        c) Price(s) and volume(s) Price(s) Volume(s) NOK {price} {quantity} d) Aggregated information
        e) Date of the transaction 2026-09-03; 21:30 CEST f) Place of the transaction Outside trading venue"""
        text = template.format(nature="Allocation of shares in private placement", price="4.80", quantity="5,208,333") + "\n" + template.format(nature="Share lending in connection with settlement", price="0", quantity="57,291,667")
        filing = _thor_forms({"messageId": 681637, "issuerName": "Thor Medical ASA"}, text)
        self.assertEqual([group["action"] for group in filing["transaction_groups"]], ["acquisition", "transfer"])
        self.assertEqual(filing["transaction_groups"][1]["consideration"], "none")
        self.assertEqual([group["instrument"]["isin_raw"] for group in filing["transaction_groups"]], ["NO0010597883", "NO0010597883"])

    def test_bafin_search_and_party_identity(self):
        search = '''<html><form id="sucheForm"></form><h2>Auswahl Emittent</h2><table id="emittent"><tbody><tr>
        <td><a href="ergebnisListe.do?cmd=loadMeldepflichtigeAction&amp;emittentBafinId=40001573&amp;meldungId=34774">Meta Wolf AG</a></td>
        <td>40001573</td><td>DE000A254203</td><td>LUBANCO PTE. LTD.</td><td>in enger Beziehung</td><td>Aktie</td><td>Kauf</td><td>02.09.2026</td><td>Xetra</td><td>04.09.2026 08:46:39</td>
        </tr></tbody></table></html>'''
        rows, pages = bafin_search_rows(search.encode())
        self.assertEqual(pages, [])
        self.assertEqual(rows[0]["meldung_id"], "34774")
        self.assertEqual(rows[0]["published_date"], "2026-09-04")
        party = '''<html><h2>Auswahl Meldepflichtiger</h2><table id="meldepflichtiger"><tbody><tr><td>
        <a href="transaktionListe.do?cmd=loadTransaktionenAction&amp;meldungId=34774&amp;emittentBafinId=40001573&amp;meldepflichtigerId=34782&amp;KeepThis=true">LUBANCO</a>
        </td><td></td><td></td><td>in enger Beziehung</td><td>02.09.2026</td></tr></tbody></table></html>'''
        links = _party_detail_links(party.encode(), "34774", "40001573")
        self.assertEqual(links[0][0], "34782")
        self.assertNotIn("KeepThis", links[0][1])

    def test_bafin_detail_retains_monetary_volume_without_inferred_quantity(self):
        fixture = Path(__file__).parent / "fixtures" / "real" / "bafin" / "detail-34774.html"
        payload = parse_bafin(fixture.read_bytes(), {
            "native_record_id": "34774:34782", "meldung_id": "34774", "party_id": "34782",
            "url": "https://portal.mvp.bafin.de/detail", "trade_date": "02.09.2026",
            "activated_at": "04.09.2026 08:46:39", "venue": "Xetra", "position": "in enger Beziehung",
        })
        filing = payload["filings"][0]
        row = filing["transaction_groups"][0]["rows"][0]
        self.assertEqual(filing["transacting_party"]["party_type"], "legal_entity")
        self.assertEqual(row["price_amount_reported"], "5.50")
        self.assertEqual(row["consideration_reported"], "12661.00")
        self.assertIsNone(row["quantity"])

    def test_bafin_linked_instrument_is_not_misclassified_as_bond(self):
        fixture = Path(__file__).parent / "fixtures" / "real" / "bafin" / "detail-34774.html"
        data = fixture.read_bytes().replace(b">Aktie<", b">Anderes auf Aktie/schuldtitel bez. FI<", 1)
        payload = parse_bafin(data, {
            "native_record_id": "34774:34782", "meldung_id": "34774", "party_id": "34782",
            "url": "https://portal.mvp.bafin.de/detail", "trade_date": "02.09.2026",
            "activated_at": "04.09.2026 08:46:39", "venue": "Xetra", "position": "in enger Beziehung",
        })
        self.assertEqual(payload["filings"][0]["transaction_groups"][0]["instrument"]["instrument_type"], "other")

    def test_newsweb_overflow_splits_inclusive_dates(self):
        adapter = NewsWebAdapter()
        calls = []
        def search(start, end):
            calls.append((start, end))
            if start != end:
                return {"overflow": True, "messages": [{"messageId": 999}]}
            return {"overflow": False, "messages": [{"messageId": int(start[-2:]), "publishedTime": start + "T00:00:00Z"}]}
        adapter._search = search
        rows = adapter._complete_search(date(2026, 9, 7), date(2026, 9, 8))
        self.assertEqual([row["messageId"] for row in rows], [7, 8])
        self.assertEqual(calls, [("2026-09-07", "2026-09-08"), ("2026-09-07", "2026-09-07"), ("2026-09-08", "2026-09-08")])

    def test_krt_pca_uses_actual_transacting_person(self):
        replacement = "\ufffd"
        text = f"""KRT-1500
Referansenummer: abc123
1.3.1 Jeg rapporterer som / pa vegne av:
N{replacement}rst{replacement}ende person
1.5.2 Fullt navn
ANITA EXAMPLE
1.7.1 Fullt navn
Alexander Manager
1.7.2 Stilling/Rolle
CEO
2.2.1 Lei-kode
98450042CE074BB6T235
2.2.2 Foretaksnavn
Example AS
2.3.1 Instrument : Aksje
2.3.2 ISIN-kode : NO0013531616
2.4.1 Transaksjonstype : Kj{replacement}p
2.6.1 Valuta : NOK
2.8.1 Gjennomsnittlig pris per enhet : 0,34
2.8.2 Aggregert volum : 65 607
2.9.1 Angi dato : 01.09.2026
2.10.1 Handelsplass : MERK - Euronext Growth Oslo
"""
        filing = _krt_form({"messageId": 1, "issuerName": "Example AS", "correctionForMessageId": 0}, text)
        self.assertEqual(filing["transacting_party"]["name_raw"], "ANITA EXAMPLE")
        self.assertEqual(filing["transacting_party"]["related_pdmr_name_raw"], "Alexander Manager")
        self.assertEqual(filing["transacting_party"]["pdmr_or_pca"], "pca")
        self.assertEqual(filing["transaction_groups"][0]["action"], "acquisition")
        option_filing = _krt_form(
            {"messageId": 2, "issuerName": "Example AS", "correctionForMessageId": 0},
            text.replace(f"Kj{replacement}p", "Erverv av aksjeopsjon"),
        )
        option_group = option_filing["transaction_groups"][0]
        self.assertEqual((option_group["action"], option_group["instrument"]["instrument_type"]), ("acquisition", "option"))
        self.assertEqual((option_group["rows"][0]["quantity_unit"], option_group["instrument"]["underlying_isin_raw"]), ("options", "NO0013531616"))

    def test_sweden_search_count_and_report_identity(self):
        page = """<html><h1>S&#246;k Insynshandel</h1><table><thead><tr><th>Transaktionsdatum</th><th>Rapportsammanst%C3%A4llning</th></tr></thead><tbody><tr>
        <td>2026-09-08</td><td>Example AB</td><td>Manager</td><td>VD</td><td>Ja</td><td>F&#246;rv&#228;rv</td><td>B share</td><td>Aktie</td><td>SE0012345678</td><td>2026-09-07</td><td>1&#160;000</td><td>Antal</td><td>12,50</td><td>SEK</td><td></td><td><a href="/Publiceringsklient/sv-SE/Rapportsammanst%C3%A4llning/Index/A004C999-1?s%C3%B6kfunktion=Insyn">Anm&#228;lan</a></td>
        </tr></tbody></table><span class="badge badge-info">1</span></html>"""
        count, rows = _search_rows(page.encode())
        self.assertEqual(count, 1)
        self.assertEqual(rows[0]["report_version"], "A004C999-1")
        self.assertTrue(rows[0]["is_pca"])

    def test_sweden_detail_preserves_pca_and_decimal_comma(self):
        fields = {
            "Namn p&#229; anm&#228;lningsskyldig": "Holding AB", "N&#228;rst&#229;ende": "Ja",
            "Person i ledande st&#228;llning": "Manager Name", "Befattning f&#246;r person i ledande st&#228;llning": "Styrelseordf&#246;rande",
            "Ny rapportering": "Ja", "Korrigering": "Nej", "Namn p&#229; emittent": "Issuer AB", "Emittentens LEI-kod": "549300G5JY05P4PLS906",
        }
        field_html = "".join(f'<div class="col-sm-4 text-right">{key}</div><div class="col-sm-6">{value}</div>' for key, value in fields.items())
        cells = ["Aktie", "Issuer B", "SE0017832173", "F&#246;rv&#228;rv", '<input type="checkbox"/>', "9&#160;370", "Antal", "94,81", "SEK", "2026-09-03", "NASDAQ STOCKHOLM AB"]
        row = "<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>"
        page = f"<html><title>Rapportsammanst&#228;llning</title>{field_html}<h2>Transaktionsdetaljer</h2><table><tbody>{row}</tbody></table></html>"
        payload = parse_sweden(page.encode(), {"report_version": "A004C999-1", "url": "https://example.invalid/A004C999-1", "published_date": "2026-09-08"})
        filing = payload["filings"][0]
        self.assertEqual(filing["transacting_party"]["name_raw"], "Holding AB")
        self.assertEqual(filing["transacting_party"]["related_pdmr_name_raw"], "Manager Name")
        self.assertEqual(filing["transaction_groups"][0]["rows"][0]["price_amount_reported"], "94.81")

    def test_sweden_aggregate_reconciles_and_stays_unselected(self):
        fields = {"Namn p&#229; anm&#228;lningsskyldig": "Manager", "N&#228;rst&#229;ende": "Nej",
                  "Person i ledande st&#228;llning": "Manager", "Namn p&#229; emittent": "Issuer AB"}
        field_html = "".join(f'<div class="col-sm-4 text-right">{key}</div><div class="col-sm-6">{value}</div>' for key, value in fields.items())
        def detail(quantity, price):
            cells = ["Aktie", "Issuer B", "SE0017832173", "F&#246;rv&#228;rv", '<input type="checkbox"/>', quantity, "Antal", price, "SEK", "2026-09-03", "NASDAQ STOCKHOLM AB"]
            return "<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>"
        aggregate = ["Issuer B", "SE0017832173", "F&#246;rv&#228;rv", "2026-09-03", "NASDAQ STOCKHOLM AB", "3&#160;000 (Antal)", "11,67 SEK"]
        detail_html = detail("1&#160;000", "10,00") + detail("2&#160;000", "12,50")
        aggregate_html = "".join(f"<td>{cell}</td>" for cell in aggregate)
        page = f'<html>Rapportsammanst&#228;llning{field_html}<h2>Transaktionsdetaljer</h2><table><tbody>{detail_html}</tbody></table><h2>Aggregeringar</h2><table><tbody><tr>{aggregate_html}</tr></tbody></table></html>'
        filing = parse_sweden(page.encode(), {"report_version": "A004C999-1", "url": "https://example.invalid/A004C999-1", "published_date": "2026-09-08"})["filings"][0]
        self.assertEqual(len(filing["transaction_groups"]), 1)
        self.assertEqual(filing["transaction_groups"][0]["aggregation_reconciliation"], "matches_details")
        self.assertEqual([row["representation"] for row in filing["transaction_groups"][0]["rows"]], ["individual", "individual", "aggregate"])


if __name__ == "__main__":
    unittest.main()
