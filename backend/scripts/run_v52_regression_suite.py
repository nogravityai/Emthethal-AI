import os
import sys
import unittest
from datetime import datetime, timezone
from typing import List

# Setup python path so we can import app modules directly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.forms.models import (
    PageCompilationState,
    PageMetadata,
    OCREvidence,
    OCRWord,
    VisualPrimitiveEvidence,
    BoundingBox,
    PrimitiveType,
    DetectionMetadata,
    SemanticZone,
    ZoneType,
    AnchorCandidate,
    ValueCandidate,
    ReadingOrderSequence,
    ReadingOrderEntry,
    LayoutGrammarGraph,
    RepeatedFieldPattern,
    PatternInstance,
    HierarchicalFieldPair,
    SignalScores,
    LinkStatus,
    Provenance,
    FieldType,
    SnapResult,
    DraftOperation,
    ZoneOperation,
    FieldOperation,
    CompiledSnapshot,
    SchemaMigrationAdapter,
    FormGraph,
    FormElement,
    FormSection,
    StructuralEdge,
    StructuralConstraint,
    FormElementType,
    LayoutTopologyType,
    StructuralRelationType,
    ConstraintType,
    TopologySignature
)

from app.core.forms.compiler import (
    resolve_zone_assignment,
    PrimitiveShapeDetectorEngine,
    ReadingOrderEngine,
    resolve_option_element_label,
    LayoutGrammarEngine,
    ParentChildLinkerEngine,
    FieldTypeInferenceEngine,
    MacroHITLEditorEngine,
    LedgerOperationEngine,
    ConcurrentModificationError,
    SnapshotStore,
    SnapshotCompilerEngine,
    SnapshotRaceConditionError,
    SchemaMigrationAdapterRunner,
    generate_stable_element_id,
    StructuralSemanticCompilerEngine
)

class TestCFISv52Compiler(unittest.TestCase):

    def setUp(self):
        # Setup page metadata for tests
        self.metadata = PageMetadata(
            page_id="page_001",
            document_id="doc_123",
            page_number=1,
            width_px=1000,
            height_px=1400,
            dpi=300,
            file_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            upload_timestamp=datetime.now(timezone.utc),
            pipeline_version="CFIS-P5.2"
        )
        self.state = PageCompilationState(
            page_metadata=self.metadata,
            compiled_zones=[],
            linked_fields=[],
            inferred_types=[],
            composite_containers=[],
            snapshots=[],
            ledger_operations=[]
        )

    def test_zone_collision_resolution(self):
        """
        Tests Priority 1-5 of the Zone Collision Resolution Protocol (Rule 4).
        """
        # Create zones
        # Zone A: Parent, large
        zone_a = SemanticZone(
            zone_id="zone_A",
            zone_type=ZoneType.SECTION_HEADER,
            zone_label="Header Zone",
            bbox=BoundingBox(x_min=0, y_min=0, x_max=500, y_max=500),
            confidence=1.0,
            compiled_fields=[]
        )
        # Zone B: Subzone, deeper level
        zone_b = SemanticZone(
            zone_id="zone_B",
            zone_type=ZoneType.PATIENT_INFO,
            zone_label="Input Section B",
            bbox=BoundingBox(x_min=10, y_min=10, x_max=200, y_max=200),
            parent_zone_id="zone_A",
            confidence=1.0,
            compiled_fields=[]
        )
        # Zone C: Smallest area overlapping with Zone B
        zone_c = SemanticZone(
            zone_id="zone_C",
            zone_type=ZoneType.PATIENT_INFO,
            zone_label="Input Section C",
            bbox=BoundingBox(x_min=10, y_min=10, x_max=150, y_max=150),
            parent_zone_id="zone_A",
            confidence=1.0,
            compiled_fields=[]
        )
        zones = [zone_a, zone_b, zone_c]

        # Element strictly contained in Zone C, B, and A.
        # Should choose Zone C (smallest area since B and C have same parent depth=1)
        elem_bbox = BoundingBox(x_min=20, y_min=20, x_max=50, y_max=50)
        assigned = resolve_zone_assignment(elem_bbox, zones)
        self.assertEqual(assigned, "zone_C")

        # Element overlapping but outside C, inside B
        # bbox [160, 160, 190, 190] is contained in Zone B and Zone A. Depth of B is 1, A is 0.
        # Should choose Zone B (deepest depth)
        elem_bbox_b = BoundingBox(x_min=160, y_min=160, x_max=190, y_max=190)
        assigned_b = resolve_zone_assignment(elem_bbox_b, zones)
        self.assertEqual(assigned_b, "zone_B")

    def test_underline_vs_textline_disambiguation(self):
        """
        Tests reclassification of horizontal line to TEXTLINE if overlapping OCRWord exists (Rule 36).
        """
        engine = PrimitiveShapeDetectorEngine()
        
        # Horizontal line candidate UNDERLINE_FIELD
        line_bbox = BoundingBox(x_min=100, y_min=200, x_max=300, y_max=205)
        prim = VisualPrimitiveEvidence(
            primitive_id="prim_line_1",
            primitive_type=PrimitiveType.UNDERLINE_FIELD,
            bbox=line_bbox,
            confidence=0.9,
            detection_metadata=DetectionMetadata(
                contour_area=600.0,
                aspect_ratio=40.0
            )
        )
        
        # Case A: Word with high overlap and confidence > 0.5
        word_a = OCRWord(
            word_id="word_1",
            text="Hello",
            bbox=BoundingBox(x_min=150, y_min=198, x_max=200, y_max=204),
            confidence=0.9
        )
        
        res = engine.run([prim], [word_a])
        self.assertEqual(res[0].primitive_type, PrimitiveType.TEXTLINE)
        self.assertTrue(res[0].detection_metadata.contains_ocr_words)

        # Case B: Word with low overlap (< 50%) or low confidence (<= 0.5)
        word_b = OCRWord(
            word_id="word_2",
            text="Test",
            bbox=BoundingBox(x_min=150, y_min=198, x_max=200, y_max=204),
            confidence=0.4
        )
        res_b = engine.run([prim], [word_b])
        self.assertEqual(res_b[0].primitive_type, PrimitiveType.UNDERLINE_FIELD)

    def test_reading_order_and_median_line_height(self):
        """
        Tests reading order sequence clustering and median line height calculation.
        """
        engine = ReadingOrderEngine()
        
        # OCR Evidence with LTR direction
        ocr = OCREvidence(
            ocr_engine="paddle",
            engine_version="v2.7",
            page_direction="LTR",
            extraction_timestamp=datetime.now(timezone.utc),
            words=[
                OCRWord(word_id="w1", text="First", bbox=BoundingBox(x_min=10, y_min=100, x_max=50, y_max=120), confidence=0.9),
                OCRWord(word_id="w2", text="Second", bbox=BoundingBox(x_min=60, y_min=102, x_max=110, y_max=122), confidence=0.95),
                OCRWord(word_id="w3", text="Third", bbox=BoundingBox(x_min=10, y_min=150, x_max=50, y_max=170), confidence=0.92)
            ]
        )
        
        zone = SemanticZone(
            zone_id="zone_1",
            zone_type=ZoneType.PATIENT_INFO,
            zone_label="Main",
            bbox=BoundingBox(x_min=0, y_min=0, x_max=500, y_max=500),
            confidence=1.0,
            compiled_fields=[]
        )
        
        reading_order, updated_zones = engine.run(ocr, [zone])
        
        self.assertEqual(len(reading_order.entries), 3)
        self.assertEqual(updated_zones[0].median_line_height_px, 20.0) # all word heights are 20px
        
        # Verify LTR sorting
        # Line 0: w1 (x=10), w2 (x=60)
        # Line 1: w3 (x=10)
        w1_entry = next(e for e in reading_order.entries if e.word_id == "w1")
        w2_entry = next(e for e in reading_order.entries if e.word_id == "w2")
        w3_entry = next(e for e in reading_order.entries if e.word_id == "w3")
        
        self.assertEqual(w1_entry.line_index, 0)
        self.assertEqual(w1_entry.position_in_line, 0)
        self.assertEqual(w2_entry.line_index, 0)
        self.assertEqual(w2_entry.position_in_line, 1)
        self.assertEqual(w3_entry.line_index, 1)
        self.assertEqual(w3_entry.position_in_line, 0)

    def test_option_element_label_resolution(self):
        """
        Tests OptionElement label resolution within 20px horizontal margin (Gap#37).
        """
        # Option primitive
        opt_bbox = BoundingBox(x_min=100, y_min=100, x_max=110, y_max=110)
        
        # LTR Case: Search to the right
        words_ltr = [
            OCRWord(word_id="w_yes", text="Yes", bbox=BoundingBox(x_min=115, y_min=102, x_max=128, y_max=108), confidence=0.9),
            OCRWord(word_id="w_far", text="Far", bbox=BoundingBox(x_min=140, y_min=102, x_max=160, y_max=108), confidence=0.8)
        ]
        
        label_text, label_ids = resolve_option_element_label(opt_bbox, words_ltr, [], direction="LTR")
        # Yes is at 115, which is within [110, 130]. Far is at 140, which is outside.
        self.assertEqual(label_text, "Yes")
        self.assertEqual(label_ids, ["w_yes"])

        # RTL Case: Search to the left
        words_rtl = [
            OCRWord(word_id="w_no", text="لا", bbox=BoundingBox(x_min=85, y_min=102, x_max=95, y_max=108), confidence=0.95)
        ]
        label_text_rtl, label_ids_rtl = resolve_option_element_label(opt_bbox, words_rtl, [], direction="RTL")
        # لا is at x_max=95, which is within [80, 100].
        self.assertEqual(label_text_rtl, "لا")
        self.assertEqual(label_ids_rtl, ["w_no"])

    def test_parent_child_linker_and_signals(self):
        """
        Tests SignalScores and LinkStatus classification in ParentChildLinkerEngine.
        """
        linker = ParentChildLinkerEngine()
        
        anchors = [
            AnchorCandidate(
                primitive_id="a1",
                text_ids=["w_name"],
                bbox=BoundingBox(x_min=100, y_min=100, x_max=150, y_max=120)
            )
        ]
        values = [
            ValueCandidate(
                primitive_id="v1",
                bbox=BoundingBox(x_min=160, y_min=100, x_max=250, y_max=120),
                candidate_type=PrimitiveType.UNDERLINE_FIELD
            )
        ]
        zones = [
            SemanticZone(
                zone_id="zone_1",
                zone_type=ZoneType.PATIENT_INFO,
                zone_label="Main",
                bbox=BoundingBox(x_min=0, y_min=0, x_max=500, y_max=500),
                confidence=1.0,
                compiled_fields=[]
            )
        ]
        
        reading_order = ReadingOrderSequence(
            entries=[
                ReadingOrderEntry(word_id="w_name", line_index=0, position_in_line=0, resolved_direction="LTR", zone_id="zone_1")
            ],
            page_id="page_001",
            computed_at=datetime.now(timezone.utc)
        )
        
        pairs = linker.run(anchors, values, zones, reading_order)
        self.assertEqual(len(pairs), 1)
        # Verify confirmed or tentative status based on spatial proximity
        self.assertIn(pairs[0].status, [LinkStatus.LINK_CONFIRMED, LinkStatus.LINK_TENTATIVE])
        self.assertTrue(pairs[0].signal_scores.final_score > 0.5)

    def test_adaptive_snapping_radius(self):
        """
        Tests adaptive snapping radius scaling based on zone.median_line_height_px (Gap#17).
        """
        engine = FieldTypeInferenceEngine()
        
        # Scenario A: median_line_height = 25px
        # primary = max(15, 0.8 * 25) = 20.0px
        # expanded = max(30, 1.6 * 25) = 40.0px
        zone_a = SemanticZone(
            zone_id="zone_1",
            zone_type=ZoneType.PATIENT_INFO,
            zone_label="Z1",
            bbox=BoundingBox(x_min=0, y_min=0, x_max=500, y_max=500),
            confidence=1.0,
            compiled_fields=[],
            median_line_height_px=25.0
        )
        
        anchor = AnchorCandidate(
            primitive_id="a1",
            bbox=BoundingBox(x_min=100, y_min=100, x_max=120, y_max=120)
        )
        
        # Center = (110, 110)
        # Value at distance 15px (within 20px) -> EXACT
        value_exact = ValueCandidate(
            primitive_id="v1",
            bbox=BoundingBox(x_min=125, y_min=100, x_max=135, y_max=120),
            candidate_type=PrimitiveType.UNDERLINE_FIELD
        )
        
        pair = HierarchicalFieldPair(
            pair_id="pair_1",
            question_anchor_id="a1",
            answer_node_id="v1",
            status=LinkStatus.LINK_CONFIRMED,
            signal_scores=SignalScores(final_score=0.9),
            zone_id="zone_1",
            provenance=Provenance(source_engine="test", confidence=0.9, evidence_refs=[], creation_timestamp=datetime.now(timezone.utc))
        )
        
        inference_exact = engine.run(pair, anchor, value_exact, zone_a)
        self.assertEqual(inference_exact.snap_result, SnapResult.EXACT)
        self.assertEqual(inference_exact.snap_radius_used_px, 20.0)

        # Value at distance 30px (between 20px and 40px) -> LOW_CONFIDENCE
        # Value center at (140, 110) -> distance = 30px
        value_low = ValueCandidate(
            primitive_id="v2",
            bbox=BoundingBox(x_min=135, y_min=100, x_max=145, y_max=120),
            candidate_type=PrimitiveType.UNDERLINE_FIELD
        )
        pair_low = pair.model_copy(update={"answer_node_id": "v2"})
        inference_low = engine.run(pair_low, anchor, value_low, zone_a)
        self.assertEqual(inference_low.snap_result, SnapResult.LOW_CONFIDENCE)

    def test_draft_operation_lifecycle_and_locks(self):
        """
        Tests HITL draft edits lifecycle, advisory soft-locking, and commit/discard (Gap#24).
        """
        hitl_manager = MacroHITLEditorEngine()
        
        # Start session A
        draft_a, warn_a = hitl_manager.start_draft("session_A", "page_001")
        self.assertIsNone(warn_a)
        self.assertEqual(draft_a.status, "PENDING")
        
        # Add operation
        op_zone = {
            "operation_id": "op_uuid_1",
            "operator_id": "operator_test",
            "operation_type": "CREATE_ZONE",
            "ledger_sequence_number": 0,
            "target_zone_id": "new_zone_123",
            "parameters": {
                "zone_type": "patient_info",
                "zone_label": "Adhoc Zone",
                "bbox": {"x_min": 100, "y_min": 100, "x_max": 200, "y_max": 200}
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        hitl_manager.add_operation("session_A", op_zone)
        
        # Try session B on same page -> should get warning
        draft_b, warn_b = hitl_manager.start_draft("session_B", "page_001")
        self.assertIsNotNone(warn_b)
        self.assertIn("DraftConflictWarning", warn_b)
        
        # Commit session A
        ledger_engine = LedgerOperationEngine()
        mutated_state = hitl_manager.commit_draft("session_A", ledger_engine, self.state)
        
        # Verify zone was created in state
        self.assertEqual(len(mutated_state.compiled_zones), 1)
        self.assertEqual(mutated_state.compiled_zones[0].zone_id, "new_zone_123")
        self.assertEqual(draft_a.status, "COMMITTED")

    def test_concurrent_modification_and_hash(self):
        """
        Tests LedgerOperationEngine sequence validation (Gap#26) and state hash recomputation (Gap#20).
        """
        engine = LedgerOperationEngine()
        
        op = ZoneOperation(
            operation_id="op_uuid_2",
            operator_id="operator_test",
            operation_type="CREATE_ZONE",
            ledger_sequence_number=1, # wrong sequence, should be 0
            target_zone_id="z_test",
            parameters={
                "bbox": {"x_min": 0, "y_min": 0, "x_max": 100, "y_max": 100}
            },
            timestamp=datetime.now(timezone.utc)
        )
        
        # Assert raises error
        with self.assertRaises(ConcurrentModificationError):
            engine.commit(self.state, op)
            
        # Commit correct sequence
        op_correct = op.model_copy(update={"ledger_sequence_number": 0})
        new_state = engine.commit(self.state, op_correct)
        
        self.assertEqual(len(new_state.ledger_operations), 1)
        self.assertIsNotNone(new_state.state_hash)

    def test_large_container_partitioning(self):
        """
        Tests RepeatedFieldPattern > 50 instances triggering LargeContainerPartitioningStrategy.
        """
        engine = LayoutGrammarEngine()
        
        # Create a pattern with 55 instances
        instances = [
            PatternInstance(instance_index=i, element_ids=[f"elem_{i}"])
            for i in range(55)
        ]
        
        pattern = RepeatedFieldPattern(
            pattern_id="pat_1",
            template_fields=["field_a"],
            instances=instances
        )
        
        graph = LayoutGrammarGraph(patterns=[pattern])
        res = engine.run(graph)
        
        # Verify that all 55 instances are preserved and sorted
        self.assertEqual(len(res.patterns[0].instances), 55)
        self.assertEqual(res.patterns[0].instances[0].instance_index, 0)
        self.assertEqual(res.patterns[0].instances[-1].instance_index, 54)

    def test_snapshot_compiler_eviction(self):
        """
        Tests CompiledSnapshot storage and memory cache eviction of 3 snapshot limit (Gap#34).
        """
        store = SnapshotStore()
        compiler = SnapshotCompilerEngine(store)
        
        # Base state
        state = self.state
        ledger_engine = LedgerOperationEngine()
        
        # Compile 4 snapshots sequentially (requires committing operations to change sequence number)
        states = []
        for i in range(4):
            op = ZoneOperation(
                operation_id=f"op_uuid_evict_{i}",
                operator_id="operator_test",
                operation_type="CREATE_ZONE",
                ledger_sequence_number=i,
                target_zone_id=f"z_{i}",
                parameters={"bbox": {"x_min": 0, "y_min": 0, "x_max": 100, "y_max": 100}},
                timestamp=datetime.now(timezone.utc)
            )
            state = ledger_engine.commit(state, op)
            state = compiler.compile(state)
            states.append(state)
            
        # Verify all 4 are in store
        self.assertEqual(len(store.blobs), 4)
        
        # Verify in-memory cache limit of 3. Oldest (seq 1, snap_page_001_seq_1) should be evicted
        self.assertEqual(len(compiler.memory_cache), 3)
        self.assertNotIn("snap_page_001_seq_1", compiler.memory_cache)
        
        # Loading the evicted snapshot should load it back from store
        loaded = compiler.load_snapshot("snap_page_001_seq_1")
        self.assertEqual(loaded.ledger_sequence_number, 1)
        self.assertIn("snap_page_001_seq_1", compiler.memory_cache)

    def test_schema_migration(self):
        """
        Tests SchemaMigrationAdapter remapping and dropping fields (Gap#12).
        """
        runner = SchemaMigrationAdapterRunner()
        
        # Source snapshot in v1.0
        snap = CompiledSnapshot(
            snapshot_id="snap_1",
            page_id="page_001",
            ledger_sequence_number=1,
            compiled_zones=[],
            compiled_fields=[
                HierarchicalFieldPair(
                    pair_id="pair_old_tag",
                    question_anchor_id="a",
                    answer_node_id="v",
                    status=LinkStatus.LINK_CONFIRMED,
                    signal_scores=SignalScores(final_score=0.95),
                    zone_id="z",
                    provenance=Provenance(source_engine="test", confidence=0.9, evidence_refs=[], creation_timestamp=datetime.now(timezone.utc))
                ),
                HierarchicalFieldPair(
                    pair_id="pair_to_drop",
                    question_anchor_id="b",
                    answer_node_id="w",
                    status=LinkStatus.LINK_CONFIRMED,
                    signal_scores=SignalScores(final_score=0.95),
                    zone_id="z",
                    provenance=Provenance(source_engine="test", confidence=0.9, evidence_refs=[], creation_timestamp=datetime.now(timezone.utc))
                )
            ],
            composite_containers=[],
            schema_version="v1.0",
            created_at=datetime.now(timezone.utc)
        )
        
        # Migration adapter mapping
        adapter = SchemaMigrationAdapter(
            from_version="v1.0",
            to_version="v1.1",
            migration_steps=[
                {"action": "rename", "field_tag": "pair_old_tag", "new_tag": "pair_new_tag"},
                {"action": "drop", "field_tag": "pair_to_drop"}
            ]
        )
        
        migrated = runner.run(snap, adapter)
        
        self.assertEqual(migrated.schema_version, "v1.1")
        self.assertEqual(len(migrated.compiled_fields), 1)
        self.assertEqual(migrated.compiled_fields[0].pair_id, "pair_new_tag")



# ─── PHASE 3: Smart Zone & Token Orchestration ───────────────────────────────

class TestSmartZoneOrchestration(unittest.TestCase):
    """
    Regression suite for SmartZoneDiscoveryEngine (Phase 3).
    Covers:
      1. Coordinate drift correction via resolve_zone_assignment(drift_offset=...)
      2. Adaptive RTL/LTR direction detection
      3. Full engine integration — clustering, anchor calibration, ledger ops
    """

    def _make_metadata(self) -> PageMetadata:
        return PageMetadata(
            page_id="page_smart_001",
            document_id="doc_smart",
            page_number=1,
            width_px=1200,
            height_px=1600,
            dpi=300,
            file_hash="abc123",
            upload_timestamp=datetime.now(timezone.utc),
            pipeline_version="CFIS-P5.3",
        )

    def _make_state(self, metadata: PageMetadata, zones=None, ocr=None) -> PageCompilationState:
        return PageCompilationState(
            page_metadata=metadata,
            compiled_zones=zones or [],
            linked_fields=[],
            inferred_types=[],
            composite_containers=[],
            snapshots=[],
            ledger_operations=[],
            ocr_evidence=ocr,
        )

    # ── Test 1: Coordinate Drift in resolve_zone_assignment ────────────────────

    def test_drift_offset_shifts_assignment(self):
        """
        A word that sits just OUTSIDE zone_right without drift should be unassigned.
        With drift_offset=(+50, 0) the word's virtual bbox moves INTO zone_right
        and should be correctly assigned — without mutating the original BoundingBox.
        """
        zone_left = SemanticZone(
            zone_id="zone_left",
            zone_type=ZoneType.PATIENT_INFO,
            zone_label="Left Zone",
            bbox=BoundingBox(x_min=0, y_min=0, x_max=200, y_max=100),
            confidence=1.0,
        )
        zone_right = SemanticZone(
            zone_id="zone_right",
            zone_type=ZoneType.FREE_TEXT,
            zone_label="Right Zone",
            bbox=BoundingBox(x_min=250, y_min=0, x_max=500, y_max=100),
            confidence=1.0,
        )
        zones = [zone_left, zone_right]

        # Word at x=[210, 240] — between the two zones, assigned to NONE without drift
        word_bbox = BoundingBox(x_min=210, y_min=10, x_max=240, y_max=50)
        no_drift = resolve_zone_assignment(word_bbox, zones)
        self.assertIsNone(no_drift, "Without drift the word should be unassigned")

        # With +50px drift the virtual bbox becomes [260, 10, 290, 50] → inside zone_right
        with_drift = resolve_zone_assignment(word_bbox, zones, drift_offset=(50.0, 0.0))
        self.assertEqual(with_drift, "zone_right",
                         "Drift offset should shift the word into zone_right")

        # Verify the original BoundingBox is NOT mutated
        self.assertEqual(word_bbox.x_min, 210)
        self.assertEqual(word_bbox.x_max, 240)

    # ── Test 2: Adaptive Direction Detection ──────────────────────────────────

    def test_adaptive_direction_rtl_dominant(self):
        """
        When a zone contains more RTL-tagged words than LTR ones,
        SmartZoneDiscoveryEngine._detect_zone_direction must return 'RTL'.
        """
        from app.core.forms.compiler import SmartZoneDiscoveryEngine

        engine = SmartZoneDiscoveryEngine()
        zone = SemanticZone(
            zone_id="zone_rtl",
            zone_type=ZoneType.PATIENT_INFO,
            zone_label="Arabic Section",
            bbox=BoundingBox(x_min=0, y_min=0, x_max=600, y_max=200),
            confidence=1.0,
        )
        words = [
            OCRWord(word_id="w1", text="اسم", bbox=BoundingBox(x_min=10, y_min=10, x_max=60, y_max=30), confidence=0.98, direction="RTL"),
            OCRWord(word_id="w2", text="المريض", bbox=BoundingBox(x_min=70, y_min=10, x_max=150, y_max=30), confidence=0.97, direction="RTL"),
            OCRWord(word_id="w3", text=":", bbox=BoundingBox(x_min=155, y_min=10, x_max=165, y_max=30), confidence=0.99, direction="LTR"),
        ]
        direction = engine._detect_zone_direction(zone, words)
        self.assertEqual(direction, "RTL",
                         "Arabic-dominant zone should resolve to RTL")

    def test_adaptive_direction_ltr_dominant(self):
        """LTR-dominant zone returns 'LTR'."""
        from app.core.forms.compiler import SmartZoneDiscoveryEngine

        engine = SmartZoneDiscoveryEngine()
        zone = SemanticZone(
            zone_id="zone_ltr",
            zone_type=ZoneType.SECTION_HEADER,
            zone_label="English Header",
            bbox=BoundingBox(x_min=0, y_min=0, x_max=600, y_max=200),
            confidence=1.0,
        )
        words = [
            OCRWord(word_id="e1", text="Patient", bbox=BoundingBox(x_min=10, y_min=10, x_max=80, y_max=30), confidence=0.99, direction="LTR"),
            OCRWord(word_id="e2", text="Name", bbox=BoundingBox(x_min=85, y_min=10, x_max=140, y_max=30), confidence=0.98, direction="LTR"),
            OCRWord(word_id="e3", text=":", bbox=BoundingBox(x_min=145, y_min=10, x_max=155, y_max=30), confidence=0.99, direction="LTR"),
        ]
        direction = engine._detect_zone_direction(zone, words)
        self.assertEqual(direction, "LTR")

    # ── Test 3: SmartZoneDiscoveryEngine full integration ────────────────────

    def test_smart_zone_engine_full_run(self):
        """
        Full integration:
          - OCR words that form two spatial clusters → engine discovers 2 dynamic zones
          - One zone has 'اسم المريض' (patient name) keyword → anchor calibration fires
          - Ledger records CREATE_ZONE + CALIBRATE_COORDINATES operations
          - Each zone.metadata['direction'] is populated
        """
        from app.core.forms.compiler import SmartZoneDiscoveryEngine

        metadata = self._make_metadata()

        # Two clusters: cluster A (patient header) and cluster B (checkbox area)
        ocr = OCREvidence(
            ocr_engine="paddle",
            extraction_timestamp=datetime.now(timezone.utc),
            page_direction="RTL",
            words=[
                # Cluster A — patient info block
                OCRWord(word_id="c1w1", text="اسم المريض", bbox=BoundingBox(x_min=50, y_min=50, x_max=200, y_max=80), confidence=0.99, direction="RTL"),
                OCRWord(word_id="c1w2", text="محمد أحمد", bbox=BoundingBox(x_min=210, y_min=52, x_max=360, y_max=78), confidence=0.96, direction="RTL"),
                OCRWord(word_id="c1w3", text="العمر:", bbox=BoundingBox(x_min=50, y_min=100, x_max=130, y_max=128), confidence=0.97, direction="RTL"),
                OCRWord(word_id="c1w4", text="42", bbox=BoundingBox(x_min=140, y_min=100, x_max=180, y_max=128), confidence=0.95, direction="LTR"),
                # Cluster B — checkbox block (far below cluster A)
                OCRWord(word_id="c2w1", text="☑", bbox=BoundingBox(x_min=50, y_min=400, x_max=75, y_max=425), confidence=0.99, direction="LTR"),
                OCRWord(word_id="c2w2", text="موافق", bbox=BoundingBox(x_min=85, y_min=400, x_max=180, y_max=425), confidence=0.95, direction="RTL"),
                OCRWord(word_id="c2w3", text="على", bbox=BoundingBox(x_min=185, y_min=400, x_max=225, y_max=425), confidence=0.94, direction="RTL"),
            ],
        )

        # A pre-existing template zone for patient_info that is slightly offset
        # (simulating scanning drift). The engine will calibrate the drift.
        template_zone = SemanticZone(
            zone_id="zone_patient",
            zone_type=ZoneType.PATIENT_INFO,
            zone_label="patient_info",  # matches DEFAULT_ANCHOR_KEYWORDS key
            bbox=BoundingBox(x_min=40, y_min=40, x_max=380, y_max=140),  # template coords
            confidence=0.9,
        )

        state = self._make_state(metadata, zones=[template_zone], ocr=ocr)

        engine = SmartZoneDiscoveryEngine(v_gap_threshold=30, h_gap_threshold=50)
        new_state = engine.run(state, operator_id="test_suite")

        # ── Assertion 1: dynamic zones were discovered ────────────────────
        dynamic_zones = [z for z in new_state.compiled_zones if z.is_dynamic]
        self.assertGreaterEqual(len(dynamic_zones), 1,
                                "Engine should discover at least one dynamic zone from OCR clusters")

        # ── Assertion 2: anchor calibration was applied to the template zone ─
        patient_zone = next(
            (z for z in new_state.compiled_zones if z.zone_id == "zone_patient"), None
        )
        self.assertIsNotNone(patient_zone)
        self.assertIsNotNone(patient_zone.coordinate_drift,
                             "Anchor calibration should set coordinate_drift on the template zone")
        dx, dy = patient_zone.coordinate_drift
        # The OCR anchor 'اسم المريض' is at ~(125, 65); zone center is at (210, 90).
        # So dx ≈ 125-210 = -85, dy ≈ 65-90 = -25 (approximate, sign depends on anchor pos)
        self.assertIsInstance(dx, float)
        self.assertIsInstance(dy, float)
        self.assertGreater(len(patient_zone.anchors_refs), 0,
                           "Calibrated zone must record the anchor word_ids")

        # ── Assertion 3: ledger records calibration ops ──────────────────
        cal_ops = [
            op for op in new_state.ledger_operations
            if hasattr(op, "operation_type") and op.operation_type == "CALIBRATE_COORDINATES"
        ]
        self.assertGreaterEqual(len(cal_ops), 1,
                                "At least one CALIBRATE_COORDINATES op must be in the ledger")

        # ── Assertion 4: all zones have direction metadata ───────────────
        for z in new_state.compiled_zones:
            self.assertIn("direction", z.metadata,
                          f"Zone {z.zone_id} should have 'direction' in metadata")
            self.assertIn(z.metadata["direction"], ("LTR", "RTL"))

        # ── Assertion 5: new dynamic zones emitted CREATE_ZONE ops ──────
        create_ops = [
            op for op in new_state.ledger_operations
            if hasattr(op, "operation_type") and op.operation_type == "CREATE_ZONE"
        ]
        self.assertEqual(len(create_ops), len(dynamic_zones),
                         "One CREATE_ZONE op per newly discovered zone")


class TestStructuralSemanticCompiler(unittest.TestCase):
    def setUp(self):
        self.metadata = PageMetadata(
            page_id="page_smart_999",
            document_id="doc_smart_999",
            page_number=1,
            width_px=1000,
            height_px=1400,
            dpi=300,
            file_hash="xyz789",
            upload_timestamp=datetime.now(timezone.utc),
            pipeline_version="CFIS-P5.2"
        )
        self.section_zone = SemanticZone(
            zone_id="zone_header_1",
            zone_type=ZoneType.SECTION_HEADER,
            zone_label="نوع الولادة",
            bbox=BoundingBox(x_min=50, y_min=100, x_max=500, y_max=140),
            confidence=1.0,
            median_line_height_px=20.0
        )
        self.options_zone = SemanticZone(
            zone_id="zone_options_1",
            zone_type=ZoneType.CHECKBOX_GROUP,
            zone_label="نوع الولادة خيارات",
            bbox=BoundingBox(x_min=50, y_min=150, x_max=500, y_max=300),
            confidence=1.0,
            median_line_height_px=20.0
        )
        
        self.prim_cb_1 = VisualPrimitiveEvidence(
            primitive_id="prim_cb_1",
            primitive_type=PrimitiveType.CHECKBOX,
            bbox=BoundingBox(x_min=60, y_min=180, x_max=80, y_max=200),
            confidence=0.9
        )
        self.prim_cb_2 = VisualPrimitiveEvidence(
            primitive_id="prim_cb_2",
            primitive_type=PrimitiveType.CHECKBOX,
            bbox=BoundingBox(x_min=200, y_min=180, x_max=220, y_max=200),
            confidence=0.95
        )
        self.prim_underline = VisualPrimitiveEvidence(
            primitive_id="prim_under_1",
            primitive_type=PrimitiveType.UNDERLINE_FIELD,
            bbox=BoundingBox(x_min=250, y_min=250, x_max=400, y_max=260),
            confidence=0.9
        )
        
        self.ocr = OCREvidence(
            ocr_engine="paddle",
            extraction_timestamp=datetime.now(timezone.utc),
            words=[
                OCRWord(word_id="w_nat", text="طبيعية", bbox=BoundingBox(x_min=90, y_min=180, x_max=150, y_max=200), confidence=0.9, direction="RTL"),
                OCRWord(word_id="w_ces", text="قيصرية", bbox=BoundingBox(x_min=230, y_min=180, x_max=290, y_max=200), confidence=0.95, direction="RTL"),
                OCRWord(word_id="w_ref", text="خارجي (إحالة)", bbox=BoundingBox(x_min=60, y_min=250, x_max=180, y_max=270), confidence=0.92, direction="RTL"),
                OCRWord(word_id="w_fac", text="اسم المرفق المحال منه", bbox=BoundingBox(x_min=250, y_min=230, x_max=390, y_max=245), confidence=0.91, direction="RTL")
            ]
        )
        
        prov_1 = Provenance(source_engine="test", confidence=0.9, evidence_refs=["w_nat", "prim_cb_1"], creation_timestamp=datetime.now(timezone.utc))
        prov_2 = Provenance(source_engine="test", confidence=0.95, evidence_refs=["w_ces", "prim_cb_2"], creation_timestamp=datetime.now(timezone.utc))
        prov_3 = Provenance(source_engine="test", confidence=0.88, evidence_refs=["w_ref", "prim_under_1"], creation_timestamp=datetime.now(timezone.utc))
        
        self.linked_fields = [
            HierarchicalFieldPair(
                pair_id="pair_طبيعية",
                question_anchor_id="w_nat",
                answer_node_id="prim_cb_1",
                status=LinkStatus.LINK_CONFIRMED,
                signal_scores=SignalScores(final_score=0.9),
                zone_id="zone_options_1",
                provenance=prov_1
            ),
            HierarchicalFieldPair(
                pair_id="pair_قيصرية",
                question_anchor_id="w_ces",
                answer_node_id="prim_cb_2",
                status=LinkStatus.LINK_CONFIRMED,
                signal_scores=SignalScores(final_score=0.95),
                zone_id="zone_options_1",
                provenance=prov_2
            ),
            HierarchicalFieldPair(
                pair_id="pair_خارجي",
                question_anchor_id="w_ref",
                answer_node_id="prim_cb_2",
                status=LinkStatus.LINK_CONFIRMED,
                signal_scores=SignalScores(final_score=0.8),
                zone_id="zone_options_1",
                provenance=prov_2
            ),
            HierarchicalFieldPair(
                pair_id="pair_مرفق",
                question_anchor_id="w_fac",
                answer_node_id="prim_under_1",
                status=LinkStatus.LINK_CONFIRMED,
                signal_scores=SignalScores(final_score=0.88),
                zone_id="zone_options_1",
                provenance=prov_3
            )
        ]
        
        self.state = PageCompilationState(
            page_metadata=self.metadata,
            compiled_zones=[self.section_zone, self.options_zone],
            visual_primitives=[self.prim_cb_1, self.prim_cb_2, self.prim_underline],
            ocr_evidence=self.ocr,
            linked_fields=self.linked_fields,
            inferred_types=[],
            composite_containers=[],
            snapshots=[],
            ledger_operations=[]
        )

    def test_deterministic_id_generation(self):
        """Tests that generate_stable_element_id is robust to minor coordinate shift."""
        bbox_1 = BoundingBox(x_min=100, y_min=150, x_max=120, y_max=170)
        bbox_shifted = BoundingBox(x_min=102, y_min=151, x_max=122, y_max=171)
        
        id_1 = generate_stable_element_id("page_1", bbox_1, FormElementType.ATOMIC_FIELD, "طبيعية")
        id_shifted = generate_stable_element_id("page_1", bbox_shifted, FormElementType.ATOMIC_FIELD, "طبيعية ")
        
        self.assertEqual(id_1, id_shifted, "Deterministic element ID must absorb bbox jitter and whitespace/diacritic noise")

    def test_semantic_compiler_engine_runs(self):
        """Runs the compiler engine and asserts the correctness of the generated FormGraph."""
        compiler = StructuralSemanticCompilerEngine()
        new_state = compiler.run(self.state)
        
        graph = new_state.form_graph
        self.assertIsNotNone(graph)
        self.assertEqual(graph.page_id, "page_smart_999")
        
        self.assertEqual(len(graph.sections), 1)
        self.assertEqual(graph.sections[0].label, "نوع الولادة")
        
        enum_groups = [el for el in graph.elements.values() if el.element_type == FormElementType.ENUM_GROUP]
        self.assertGreaterEqual(len(enum_groups), 1)
        
        self.assertEqual(enum_groups[0].metadata.get("selection_mode"), "SINGLE")
        
        mutex_constraints = [c for c in graph.constraints if c.constraint_type == ConstraintType.MUTUALLY_EXCLUSIVE]
        self.assertEqual(len(mutex_constraints), 1)
        
        active_edges = [e for e in graph.edges if e.relation_type == StructuralRelationType.ACTIVATES]
        self.assertGreaterEqual(len(active_edges), 1)


if __name__ == "__main__":
    unittest.main()

