# © 2018 James R. Barlow: github.com/jbarlow83
#
# This file is part of OCRmyPDF.
#
# OCRmyPDF is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# OCRmyPDF is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with OCRmyPDF.  If not, see <http://www.gnu.org/licenses/>.


import datetime
from datetime import timezone
import logging
import mmap
from os import fspath
from pathlib import Path
from shutil import copyfile, move
from unittest.mock import MagicMock, patch

import pytest

import pikepdf
from ocrmypdf._jobcontext import JobContext
from ocrmypdf.exceptions import ExitCode
from ocrmypdf.pdfa import SRGB_ICC_PROFILE, file_claims_pdfa, generate_pdfa_ps
from pikepdf.models.metadata import decode_pdf_date

try:
    import fitz
except ImportError:
    fitz = None

# pytest.helpers is dynamic
# pylint: disable=no-member
# pylint: disable=w0612

pytestmark = pytest.mark.filterwarnings('ignore:.*XMLParser.*:DeprecationWarning')

check_ocrmypdf = pytest.helpers.check_ocrmypdf
run_ocrmypdf = pytest.helpers.run_ocrmypdf
spoof = pytest.helpers.spoof


@pytest.mark.parametrize("output_type", ['pdfa', 'pdf'])
def test_preserve_metadata(spoof_tesseract_noop, output_type, resources, outpdf):
    pdf_before = pikepdf.open(resources / 'graph.pdf')

    output = check_ocrmypdf(
        resources / 'graph.pdf',
        outpdf,
        '--output-type',
        output_type,
        env=spoof_tesseract_noop,
    )

    pdf_after = pikepdf.open(output)

    for key in ('/Title', '/Author'):
        assert pdf_before.docinfo[key] == pdf_after.docinfo[key]

    pdfa_info = file_claims_pdfa(str(output))
    assert pdfa_info['output'] == output_type


@pytest.mark.parametrize("output_type", ['pdfa', 'pdf'])
def test_override_metadata(spoof_tesseract_noop, output_type, resources, outpdf):
    input_file = resources / 'c02-22.pdf'
    german = 'Du siehst den Wald vor lauter Bäumen nicht.'
    chinese = '孔子'

    p, out, err = run_ocrmypdf(
        input_file,
        outpdf,
        '--title',
        german,
        '--author',
        chinese,
        '--output-type',
        output_type,
        env=spoof_tesseract_noop,
    )

    assert p.returncode == ExitCode.ok, err

    before = pikepdf.open(input_file)
    after = pikepdf.open(outpdf)

    assert after.docinfo.Title == german, after.docinfo
    assert after.docinfo.Author == chinese, after.docinfo
    assert after.docinfo.get('/Keywords', '') == ''

    before_date = decode_pdf_date(str(before.docinfo.CreationDate))
    after_date = decode_pdf_date(str(after.docinfo.CreationDate))
    assert before_date == after_date

    pdfa_info = file_claims_pdfa(outpdf)
    assert pdfa_info['output'] == output_type


def test_high_unicode(spoof_tesseract_noop, resources, no_outpdf):

    # Ghostscript doesn't support high Unicode, so neither do we, to be
    # safe
    input_file = resources / 'c02-22.pdf'
    high_unicode = 'U+1030C is: 𐌌'

    p, out, err = run_ocrmypdf(
        input_file,
        no_outpdf,
        '--subject',
        high_unicode,
        '--output-type',
        'pdfa',
        env=spoof_tesseract_noop,
    )

    assert p.returncode == ExitCode.bad_args, err


@pytest.mark.skipif(not fitz, reason="test uses fitz")
@pytest.mark.parametrize('ocr_option', ['--skip-text', '--force-ocr'])
@pytest.mark.parametrize('output_type', ['pdf', 'pdfa'])
def test_bookmarks_preserved(
    spoof_tesseract_noop, output_type, ocr_option, resources, outpdf
):
    input_file = resources / 'toc.pdf'
    before_toc = fitz.Document(str(input_file)).getToC()

    check_ocrmypdf(
        input_file,
        outpdf,
        ocr_option,
        '--output-type',
        output_type,
        env=spoof_tesseract_noop,
    )

    after_toc = fitz.Document(str(outpdf)).getToC()
    print(before_toc)
    print(after_toc)
    assert before_toc == after_toc


def seconds_between_dates(date1, date2):
    return (date2 - date1).total_seconds()


@pytest.mark.parametrize('infile', ['trivial.pdf', 'jbig2.pdf'])
@pytest.mark.parametrize('output_type', ['pdf', 'pdfa'])
def test_creation_date_preserved(
    spoof_tesseract_noop, output_type, resources, infile, outpdf
):
    input_file = resources / infile

    check_ocrmypdf(
        input_file, outpdf, '--output-type', output_type, env=spoof_tesseract_noop
    )

    pdf_before = pikepdf.open(input_file)
    pdf_after = pikepdf.open(outpdf)

    before = pdf_before.trailer.get('/Info', {})
    after = pdf_after.trailer.get('/Info', {})

    if not before:
        assert after.get('/CreationDate', '') != ''
    else:
        # We expect that the creation date stayed the same
        date_before = decode_pdf_date(str(before['/CreationDate']))
        date_after = decode_pdf_date(str(after['/CreationDate']))
        assert seconds_between_dates(date_before, date_after) < 1000

    # We expect that the modified date is quite recent
    date_after = decode_pdf_date(str(after['/ModDate']))
    assert seconds_between_dates(date_after, datetime.datetime.now(timezone.utc)) < 1000


@pytest.mark.parametrize('output_type', ['pdf', 'pdfa'])
def test_xml_metadata_preserved(spoof_tesseract_noop, output_type, resources, outpdf):
    input_file = resources / 'graph.pdf'

    try:
        from libxmp import consts
        from libxmp.utils import file_to_dict
    except Exception:
        pytest.skip("libxmp not available or libexempi3 not installed")

    before = file_to_dict(str(input_file))

    check_ocrmypdf(
        input_file, outpdf, '--output-type', output_type, env=spoof_tesseract_noop
    )

    after = file_to_dict(str(outpdf))

    equal_properties = [
        'dc:contributor',
        'dc:coverage',
        'dc:creator',
        'dc:description',
        'dc:format',
        'dc:identifier',
        'dc:language',
        'dc:publisher',
        'dc:relation',
        'dc:rights',
        'dc:source',
        'dc:subject',
        'dc:title',
        'dc:type',
        'pdf:keywords',
    ]
    might_change_properties = [
        'dc:date',
        'pdf:pdfversion',
        'pdf:Producer',
        'xmp:CreateDate',
        'xmp:ModifyDate',
        'xmp:MetadataDate',
        'xmp:CreatorTool',
        'xmpMM:DocumentId',
        'xmpMM:DnstanceId',
    ]

    # Cleanup messy data structure
    # Top level is key-value mapping of namespaces to keys under namespace,
    # so we put everything in the same namespace
    def unify_namespaces(xmpdict):
        for entries in xmpdict.values():
            yield from entries

    # Now we have a list of (key, value, {infodict}). We don't care about
    # infodict. Just flatten to keys and values
    def keyval_from_tuple(list_of_tuples):
        for k, v, *_ in list_of_tuples:
            yield k, v

    before = dict(keyval_from_tuple(unify_namespaces(before)))
    after = dict(keyval_from_tuple(unify_namespaces(after)))

    for prop in equal_properties:
        if prop in before:
            assert prop in after, f'{prop} dropped from xmp'
            assert before[prop] == after[prop]

        # Certain entries like title appear as dc:title[1], with the possibility
        # of several
        propidx = f'{prop}[1]'
        if propidx in before:
            assert (
                after.get(propidx) == before[propidx]
                or after.get(prop) == before[propidx]
            )


def test_srgb_in_unicode_path(tmpdir):
    """Test that we can produce pdfmark when install path is not ASCII"""

    dstdir = Path(fspath(tmpdir)) / b'\xe4\x80\x80'.decode('utf-8')
    dstdir.mkdir()
    dst = dstdir / 'sRGB.icc'

    copyfile(SRGB_ICC_PROFILE, fspath(dst))

    with patch('ocrmypdf.pdfa.SRGB_ICC_PROFILE', new=str(dst)):
        generate_pdfa_ps(dstdir / 'out.ps')


def test_kodak_toc(resources, outpdf, spoof_tesseract_noop):
    output = check_ocrmypdf(
        resources / 'kcs.pdf', outpdf, '--output-type', 'pdf', env=spoof_tesseract_noop
    )

    p = pikepdf.open(outpdf)

    if pikepdf.Name.First in p.root.Outlines:
        assert isinstance(p.root.Outlines.First, pikepdf.Dictionary)


def test_metadata_fixup_warning(resources, outdir, caplog):
    from ocrmypdf._pipeline import metadata_fixup

    input_files = [
        str(outdir / 'graph.repaired.pdf'),
        str(outdir / 'layers.rendered.pdf'),
        str(outdir / 'pdfa.pdf'),  # It is okay that this is not a PDF/A
    ]
    for f in input_files:
        copyfile(resources / 'graph.pdf', f)

    log = logging.getLogger()
    context = MagicMock()
    metadata_fixup(
        input_files_groups=input_files,
        output_file=outdir / 'out.pdf',
        log=log,
        context=context,
    )
    for record in caplog.records:
        assert record.levelname != 'WARNING'

    # Now add some metadata that will not be copyable
    with pikepdf.open(outdir / 'graph.repaired.pdf') as graph:
        with graph.open_metadata() as meta:
            meta['prism2:publicationName'] = 'OCRmyPDF Test'
        graph.save(outdir / 'graph.repaired.modified.pdf')
    move(outdir / 'graph.repaired.modified.pdf', outdir / 'graph.repaired.pdf')

    log = logging.getLogger()
    context = MagicMock()
    metadata_fixup(
        input_files_groups=input_files,
        output_file=outdir / 'out.pdf',
        log=log,
        context=context,
    )
    assert any(record.levelname == 'WARNING' for record in caplog.records)


def test_prevent_gs_invalid_xml(resources, outdir):
    from ocrmypdf.__main__ import parser
    from ocrmypdf._pipeline import convert_to_pdfa
    from ocrmypdf.pdfa import generate_pdfa_ps
    from ocrmypdf.pdfinfo import PdfInfo

    generate_pdfa_ps(outdir / 'pdfa.ps')
    input_files = [str(outdir / 'layers.rendered.pdf'), str(outdir / 'pdfa.ps')]
    copyfile(resources / 'enron1.pdf', outdir / 'layers.rendered.pdf')
    log = logging.getLogger()
    context = JobContext()

    options = parser.parse_args(
        args=['-j', '1', '--output-type', 'pdfa-2', 'a.pdf', 'b.pdf']
    )
    context.options = options
    context.pdfinfo = PdfInfo(resources / 'enron1.pdf')

    convert_to_pdfa(
        input_files_groups=input_files,
        output_file=outdir / 'pdfa.pdf',
        log=log,
        context=context,
    )

    with open(outdir / 'pdfa.pdf', 'rb') as f:
        with mmap.mmap(
            f.fileno(), 0, flags=mmap.MAP_PRIVATE, prot=mmap.PROT_READ
        ) as mm:
            # Since the XML may be invalid, we scan instead of actually feeding it
            # to a parser.
            XMP_MAGIC = b'W5M0MpCehiHzreSzNTczkc9d'
            xmp_start = mm.find(XMP_MAGIC)
            xmp_end = mm.rfind(b'<?xpacket end', xmp_start)
            assert 0 < xmp_start < xmp_end
            assert mm.find(b'&#0;', xmp_start, xmp_end) == -1, "found escaped nul"
            assert mm.find(b'\x00', xmp_start, xmp_end) == -1
