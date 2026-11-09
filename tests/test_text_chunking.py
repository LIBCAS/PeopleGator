"""Character coverage, provenance and real ALTO/PAGE adapter regressions."""

from collections import Counter
from configparser import ConfigParser
from copy import deepcopy
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace as NS

import pytest

from people_gator.text import (
    ChunkMapping, LineAwareTextChunker, SourceLine, SourceSpan,
    TextChunkCollection, TextChunker, text_chunker_factory,
)


def document(*pages):
    return NS(page_layouts=list(pages), text_entity_clusters=["existing"])


def region(*texts, id="r", category="text"):
    return NS(id=id, category=category,
              lines=[NS(id="line", transcription=text) for text in texts])


def page(*regions, id="p", reading_order=None):
    return NS(id=id, regions=list(regions), reading_order=reading_order,
              text_entities=["existing mention"])


@pytest.mark.parametrize("method", ["LINES", "LINE_AWARE"])
def test_public_contract_and_factory(method):
    chunker = text_chunker_factory({})
    assert isinstance(chunker, TextChunker)
    assert isinstance(chunker, LineAwareTextChunker)
    assert (chunker.max_chars, chunker.overlap_chars) == (4096, 0)
    config = ConfigParser()
    config.read_dict({"chunker": {"METHOD": method, "MAX_CHARS": " 12 ", "OVERLAP_CHARS": "3"}})
    configured = text_chunker_factory(config["chunker"])
    assert (configured.max_chars, configured.overlap_chars) == (12, 3)
    assert configured.chunk_document(document()) == TextChunkCollection(())
    with pytest.raises(TypeError):
        TextChunker()


@pytest.mark.parametrize("settings,expected", [
    ({"CHUNKING_METHOD": "LINES", "CHUNKING_MAX_CHARS": "4000",
      "CHUNKING_OVERLAP_CHARS": "400"}, (4000, 400)),
    ({"chunking_max_chars": "12"}, (12, 0)),
    ({}, (4096, 0)),
])
def test_future_ner_configuration_boundary(settings, expected):
    config = ConfigParser()
    config.read_dict({"ENGINE_1": {
        "METHOD": "TEXT_ENTITY_DETECTION", "model_name": "example-model",
        "max_output_tokens": "1000", **settings,
    }})
    engine_config = config["ENGINE_1"]
    original = dict(engine_config)
    # Example adapter belongs in the future detector, not DocumentParser.
    chunker_config = {
        key.upper().removeprefix("CHUNKING_"): value
        for key, value in engine_config.items()
        if key.upper().startswith("CHUNKING_")
    }
    assert set(chunker_config) <= {"METHOD", "MAX_CHARS", "OVERLAP_CHARS"}
    assert chunker_config.get("METHOD") != engine_config["METHOD"]
    chunker = text_chunker_factory(chunker_config)
    assert isinstance(chunker, LineAwareTextChunker)
    assert (chunker.max_chars, chunker.overlap_chars) == expected
    assert dict(engine_config) == original
    with pytest.raises(ValueError):
        text_chunker_factory(engine_config)


def test_future_ner_unknown_chunking_option():
    config = ConfigParser()
    config.read_dict({"ENGINE_1": {
        "METHOD": "TEXT_ENTITY_DETECTION", "CHUNKING_MAX_CHAR": "4000",
    }})
    chunker_config = {
        key.upper().removeprefix("CHUNKING_"): value
        for key, value in config["ENGINE_1"].items()
        if key.upper().startswith("CHUNKING_")
    }
    with pytest.raises(ValueError, match="Unknown chunker option 'MAX_CHAR'"):
        text_chunker_factory(chunker_config)


@pytest.mark.parametrize("config,match", [
    (None, "mapping"), ([], "mapping"), ("LINE_AWARE", "mapping"),
    ({"METHOD": "unknown"}, "METHOD"), ({"METHOD": None}, "METHOD"),
    ({"CHUNKING_METHOD": "LINES"}, "Unknown chunker option"),
    ({"max_chars": 1, "MAX_CHARS": 2}, "Duplicate"),
    ({"MAX_CHAR": 2}, "Unknown"), ({1: 2}, "Unknown"),
    ({"MAX_CHARS": 0}, "MAX_CHARS"), ({"MAX_CHARS": -2}, "MAX_CHARS"),
    ({"MAX_CHARS": True}, "MAX_CHARS"), ({"MAX_CHARS": 2.0}, "MAX_CHARS"),
    ({"MAX_CHARS": "2.0"}, "MAX_CHARS"), ({"MAX_CHARS": "abc"}, "MAX_CHARS"),
    ({"MAX_CHARS": None}, "MAX_CHARS"), ({"OVERLAP_CHARS": -1}, "OVERLAP_CHARS"),
    ({"OVERLAP_CHARS": False}, "OVERLAP_CHARS"),
    ({"MAX_CHARS": 3, "OVERLAP_CHARS": 3}, "OVERLAP_CHARS"),
    ({"MAX_CHARS": 3, "OVERLAP_CHARS": 4}, "OVERLAP_CHARS"),
])
def test_factory_invalid(config, match):
    with pytest.raises(ValueError, match=match):
        text_chunker_factory(config)


@pytest.mark.parametrize("maximum,overlap", [(0, 0), (True, 0), (3, 3), (3, -1), (3, "1")])
def test_direct_constructor_invalid(maximum, overlap):
    with pytest.raises(ValueError):
        LineAwareTextChunker(maximum, overlap)


@pytest.mark.parametrize("texts", [
    ["a", "b", "c"], ["abcdefghi"], ["ab", "cdefghijkl", "m"],
    [" Karel\t", "Čapek 😀e\u0301", " \n\t ", "last"],
    ["\n", "\n"], [""], [],
])
@pytest.mark.parametrize("maximum", range(1, 13))
def test_exhaustive_coverage_and_exact_overlap(texts, maximum):
    source = document(page(region(*texts)))
    canonical = "\n".join(text for text in texts if text)
    for overlap in range(maximum):
        chunks = LineAwareTextChunker(maximum, overlap).chunk_document(source).chunks
        assert len(chunks) <= len(canonical)
        reconstructed = ""
        counts = Counter()
        for index, chunk in enumerate(chunks):
            assert chunk.index == index
            assert 0 < len(chunk.text) <= maximum
            assert chunk.text == canonical[chunk.page_start:chunk.page_end]
            assert chunk.mappings[0].start == 0
            assert chunk.mappings[-1].end == len(chunk.text)
            assert all(a.end == b.start for a, b in zip(chunk.mappings, chunk.mappings[1:]))
            if index:
                previous = chunks[index - 1]
                assert chunk.page_start == previous.page_end - overlap
                assert chunk.page_end > previous.page_end
                assert previous.text[-overlap:] == chunk.text[:overlap] if overlap else True
                reconstructed += chunk.text[overlap:]
            else:
                assert chunk.page_start == 0
                reconstructed += chunk.text
            for mapping in chunk.mappings:
                value = chunk.text[mapping.start:mapping.end]
                if mapping.source is None:
                    assert value == "\n"
                    assert mapping.line_start is mapping.line_end is None
                else:
                    address = mapping.source
                    assert (address.page_index, address.region_index) == (0, 0)
                    original = texts[address.line_index]
                    assert value == original[mapping.line_start:mapping.line_end]
                    assert len(value) == mapping.line_end - mapping.line_start
                    counts.update((address.line_index, i) for i in range(mapping.line_start, mapping.line_end))
        assert reconstructed == canonical
        assert set(counts) == {(line, offset) for line, text in enumerate(texts) for offset in range(len(text))}


def test_line_boundaries_and_page_policy():
    source = document(page(region("abcd", "ef", "gh")), page(region("ij")), page())
    chunks = LineAwareTextChunker(7, 0).chunk_document(source).chunks
    assert [c.text for c in chunks] == ["abcd\nef", "\ngh", "ij"]
    assert [c.page_index for c in chunks] == [0, 0, 1]
    assert [(c.page_start, c.page_end) for c in chunks] == [(0, 7), (7, 10), (0, 2)]
    assert chunks[1].mappings[0].source is None


def test_substring_mapping_and_overlap_keys():
    chunks = LineAwareTextChunker(12, 6).chunk_document(
        document(page(region("Karel Čapek", "Marie")))).chunks
    first, second = chunks[:2]
    start = first.text.index("Čapek")
    other_start = second.text.index("Čapek")
    assert first.source_spans(start, start + 5) == second.source_spans(other_start, other_start + 5)
    all_text = LineAwareTextChunker().chunk_document(document(page(region("Karel", "Čapek")))).chunks[0]
    assert all_text.text == "Karel\nČapek"
    assert all_text.resolve(3, 8) == (
        ChunkMapping(3, 5, SourceLine(0, "p", 0, "r", 0, "line"), 3, 5),
        ChunkMapping(5, 6),
        ChunkMapping(6, 8, SourceLine(0, "p", 0, "r", 1, "line"), 0, 2),
    )
    assert all_text.source_spans(3, 8) == (
        SourceSpan(SourceLine(0, "p", 0, "r", 0, "line"), 3, 5),
        SourceSpan(SourceLine(0, "p", 0, "r", 1, "line"), 0, 2),
    )
    assert all_text.source_spans(5, 6) == ()
    assert all_text.resolve(2, 2) == ()
    for start, end in [(-1, 2), (2, 1), (0, 12), (0.0, 1), (False, 1)]:
        with pytest.raises(ValueError):
            all_text.resolve(start, end)
    split = LineAwareTextChunker(4).chunk_document(document(page(region("abcdefgh")))).chunks[1]
    assert split.source_spans(1, 3)[0].start == 5
    assert split.source_spans(1, 3)[0].end == 7


def test_empty_irregular_nontext_and_immutability():
    text = region(None, "", 42, ["bad"], " \t", "Čapek😀")
    text.lines.insert(0, NS(id=None, transcription=None))
    empty_region = region()
    source = document(page(region(), region("ignored", category="image"),
                           region("ignored", category="face"), text,
                           empty_region), page())
    original = deepcopy(source)
    chunker = LineAwareTextChunker(6, 2)
    first = chunker.chunk_document(source)
    assert first == chunker.chunk_document(source)
    assert source == original
    assert first.chunks[0].text.startswith(" \t\n")
    assert first.chunks[0].mappings[0].source.region_index == 3
    assert first.chunks[0].mappings[0].source.line_index == 5
    empty_page = page()
    assert chunker.chunk_document(document(page(region()), empty_page)).chunks == ()


def test_reading_order_ids_objects_and_stable_addresses():
    a, b, c = region("A", id="a"), region("B", id="b"), region("C", id="c")
    layout = page(a, b, c, reading_order={"b": 0, "a": 1})
    source = document(layout, page(region("A", id="a")))
    original = deepcopy(source)
    chunks = LineAwareTextChunker().chunk_document(source).chunks
    assert [c.text for c in chunks] == ["B\nA\nC", "A"]
    assert source == original
    assert [m.source.region_index for m in chunks[0].mappings if m.source] == [1, 0, 2]
    assert chunks[0].source_spans(2, 3) != chunks[1].source_spans(0, 1)
    # Upstream also supports object keys. They must not replace source IDs.
    class HashableRegion:
        id = "x"
        category = None
        lines = [NS(id=None, transcription="X")]
    obj = HashableRegion()
    layout.regions.append(obj)
    layout.reading_order = {obj: -1, "b": 0}
    assert LineAwareTextChunker().chunk_document(source).chunks[0].text == "X\nB\nA\nC"
    duplicate_ids = document(page(region("a"), region("a")), page(region("a")),
                             page(region("a", "a")))
    spans = [m.source for c in LineAwareTextChunker().chunk_document(duplicate_ids).chunks
             for m in c.mappings if m.source]
    assert len(set(spans)) == 5


def test_import_and_chunking_without_runtime_dependencies(tmp_path):
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, "-I", "-S", "-c", f"""
import sys
sys.path.insert(0, {str(root)!r})
from types import SimpleNamespace as N
from people_gator.text import text_chunker_factory
line = N(id='line', transcription='OCR')
region = N(id='region', category='text', lines=[line])
page = N(id='page', reading_order=None, regions=[region])
document = N(page_layouts=[page])
assert text_chunker_factory({{}}).chunk_document(document).chunks[0].text == 'OCR'
assert not any(name in sys.modules for name in ('torch', 'cv2', 'numpy', 'openai', 'requests'))
"""], cwd=tmp_path, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("format", ["alto", "page"])
@pytest.mark.parametrize("page_count", [1, 2])
def test_real_xml_layouts(format, page_count, tmp_path, runtime_mode):
    if runtime_mode == "client":
        pytest.skip("XML layout loading requires processing extras")
    from people_gator.core.layout import PeopleGatorDocument

    fixtures = Path(__file__).parent / "resources" / "text_chunking"
    for index in range(page_count):
        (tmp_path / f"p{index}.xml").write_text((fixtures / f"input.{format}.xml").read_text())
    kwargs = {"alto_xmls_dir" if format == "alto" else "page_xmls_dir": str(tmp_path)}
    source = PeopleGatorDocument(**kwargs)
    snapshots = [(p.id, list(p.regions), [(r.id, [(l.id, l.transcription) for l in r.lines])
                  for r in p.regions]) for p in source.page_layouts]
    first = LineAwareTextChunker().chunk_document(source)
    assert first == LineAwareTextChunker().chunk_document(source)
    assert [c.text for c in first.chunks] == ["Čapek 😀\n Karel \nMarie"] * page_count
    for chunk in first.chunks:
        assert [m.source.region_id for m in chunk.mappings if m.source] == ["r2", "r1", "r1"]
        assert [m.source.line_id for m in chunk.mappings if m.source] == ["l3", "l1", "l2"]
        for mapping in chunk.mappings:
            if mapping.source:
                address = mapping.source
                p = source.page_layouts[address.page_index]
                r = p.regions[address.region_index]
                line = r.lines[address.line_index]
                assert (address.page_id, address.region_id, address.line_id) == (p.id, r.id, line.id)
                assert chunk.text[mapping.start:mapping.end] == line.transcription[mapping.line_start:mapping.line_end]
    assert snapshots == [(p.id, list(p.regions), [(r.id, [(l.id, l.transcription) for l in r.lines])
                         for r in p.regions]) for p in source.page_layouts]
    assert source.page_images == {}
