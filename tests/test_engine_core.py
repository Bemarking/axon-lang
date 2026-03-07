"""
AXON Engine — Unit Tests
==========================
Verifies the custom in-memory associative data engine:
  - SymbolTable: dictionary encoding, decode, cardinality
  - DataColumn: load, append, inverted index, compression
  - AssociationIndex: auto-link detection, path finding
  - SelectionEngine: green/amber/gray propagation
  - DataSpace: end-to-end load, select, aggregate, explore
"""

import pytest

from axon.engine.symbol_table import SymbolTable
from axon.engine.data_column import DataColumn
from axon.engine.association_index import AssociationIndex, AssociationLink
from axon.engine.selection_state import SelectionState, SelectionEngine
from axon.engine.dataspace import DataSpace


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SymbolTable
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestSymbolTable:
    """SymbolTable: dictionary encoding and decoding."""

    def test_encode_assigns_sequential_ids(self):
        st = SymbolTable("color")
        assert st.encode("red") == 0
        assert st.encode("blue") == 1
        assert st.encode("green") == 2

    def test_encode_returns_same_id_for_same_value(self):
        st = SymbolTable("color")
        id1 = st.encode("red")
        id2 = st.encode("red")
        assert id1 == id2 == 0

    def test_decode_returns_original_value(self):
        st = SymbolTable("x")
        st.encode("hello")
        st.encode("world")
        assert st.decode(0) == "hello"
        assert st.decode(1) == "world"

    def test_decode_invalid_raises(self):
        st = SymbolTable("x")
        with pytest.raises(KeyError):
            st.decode(99)

    def test_cardinality(self):
        st = SymbolTable("region")
        st.encode_column(["LATAM", "EMEA", "LATAM", "APAC", "LATAM"])
        assert st.cardinality == 3

    def test_encode_column(self):
        st = SymbolTable("region")
        encoded = st.encode_column(["USA", "Canada", "USA", "Mexico", "USA"])
        assert encoded == [0, 1, 0, 2, 0]

    def test_lookup_id_existing(self):
        st = SymbolTable("x")
        st.encode("test")
        assert st.lookup_id("test") == 0

    def test_lookup_id_missing_returns_none(self):
        st = SymbolTable("x")
        assert st.lookup_id("nonexistent") is None

    def test_bits_per_pointer_small(self):
        st = SymbolTable("x")
        st.encode_column(["a", "b"])  # 2 values → 1 bit
        assert st.bits_per_pointer() == 1

    def test_bits_per_pointer_medium(self):
        st = SymbolTable("x")
        for i in range(100):
            st.encode(f"val_{i}")
        # 100 values → ceil(log2(100)) = 7 bits
        assert st.bits_per_pointer() == 7

    def test_contains(self):
        st = SymbolTable("x")
        st.encode("present")
        assert "present" in st
        assert "absent" not in st

    def test_len(self):
        st = SymbolTable("x")
        st.encode_column([1, 2, 3, 2, 1])
        assert len(st) == 3

    def test_values_set(self):
        st = SymbolTable("x")
        st.encode_column(["a", "b", "c", "a"])
        assert st.values == {"a", "b", "c"}

    def test_symbols_dict(self):
        st = SymbolTable("x")
        st.encode_column(["x", "y"])
        assert st.symbols == {0: "x", 1: "y"}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  DataColumn
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestDataColumn:
    """DataColumn: columnar storage with inverted index."""

    def test_load_and_get(self):
        col = DataColumn("region")
        col.load(["LATAM", "EMEA", "LATAM", "APAC"])
        assert col.get(0) == "LATAM"
        assert col.get(1) == "EMEA"
        assert col.get(3) == "APAC"

    def test_row_count(self):
        col = DataColumn("x")
        col.load([1, 2, 3, 4, 5])
        assert col.row_count == 5
        assert len(col) == 5

    def test_append(self):
        col = DataColumn("x")
        col.append("a")
        col.append("b")
        col.append("a")
        assert col.row_count == 3
        assert col.get(0) == "a"
        assert col.get(2) == "a"

    def test_get_encoded(self):
        col = DataColumn("x")
        col.load(["alpha", "beta", "alpha"])
        assert col.get_encoded(0) == col.get_encoded(2)
        assert col.get_encoded(0) != col.get_encoded(1)

    def test_rows_matching_value(self):
        col = DataColumn("region")
        col.load(["LATAM", "EMEA", "LATAM", "APAC", "LATAM"])
        assert col.rows_matching_value("LATAM") == {0, 2, 4}
        assert col.rows_matching_value("EMEA") == {1}
        assert col.rows_matching_value("UNKNOWN") == set()

    def test_rows_matching_symbol_id(self):
        col = DataColumn("x")
        col.load(["a", "b", "a", "c", "a"])
        latam_id = col.symbol_table.lookup_id("a")
        assert col.rows_matching(latam_id) == {0, 2, 4}

    def test_distinct_values(self):
        col = DataColumn("x")
        col.load(["a", "b", "c", "a", "b"])
        assert col.distinct_values() == {"a", "b", "c"}

    def test_values_at_rows(self):
        col = DataColumn("x")
        col.load(["a", "b", "c", "d", "e"])
        assert col.values_at_rows({0, 2, 4}) == {"a", "c", "e"}

    def test_all_values(self):
        col = DataColumn("x")
        col.load(["x", "y", "x"])
        assert col.all_values() == ["x", "y", "x"]

    def test_cardinality(self):
        col = DataColumn("x")
        col.load(["a", "b", "c", "b", "a", "a"])
        assert col.cardinality == 3

    def test_compression_ratio_high_repetition(self):
        col = DataColumn("status")
        col.load(["active"] * 1000 + ["inactive"] * 500)
        # Very low cardinality (2) with 1500 rows → high compression
        assert col.compression_ratio > 5.0

    def test_compression_ratio_empty(self):
        col = DataColumn("x")
        assert col.compression_ratio == 1.0

    def test_get_out_of_bounds_raises(self):
        col = DataColumn("x")
        col.load(["a"])
        with pytest.raises(IndexError):
            col.get(5)

    def test_load_replaces_data(self):
        col = DataColumn("x")
        col.load(["a", "b"])
        assert col.row_count == 2
        col.load(["x", "y", "z"])
        assert col.row_count == 3
        assert col.get(0) == "x"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  AssociationIndex
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestAssociationIndex:
    """AssociationIndex: auto-link detection and path finding."""

    def test_auto_link_shared_column(self):
        idx = AssociationIndex()
        idx.register_table("Sales", ["ProductID", "Region", "Revenue"])
        links = idx.register_table("Products", ["ProductID", "Category", "Price"])
        assert len(links) == 1
        assert links[0].field_name == "ProductID"

    def test_multiple_shared_columns(self):
        idx = AssociationIndex()
        idx.register_table("A", ["x", "y", "z"])
        links = idx.register_table("B", ["x", "y", "w"])
        assert len(links) == 2
        field_names = {l.field_name for l in links}
        assert field_names == {"x", "y"}

    def test_no_shared_columns(self):
        idx = AssociationIndex()
        idx.register_table("A", ["x", "y"])
        links = idx.register_table("B", ["w", "z"])
        assert len(links) == 0

    def test_find_links(self):
        idx = AssociationIndex()
        idx.register_table("Sales", ["ProductID", "Region"])
        idx.register_table("Products", ["ProductID", "Category"])
        idx.register_table("Regions", ["Region", "Country"])

        sales_links = idx.find_links("Sales")
        assert len(sales_links) == 2

    def test_get_associated_tables(self):
        idx = AssociationIndex()
        idx.register_table("Sales", ["ProductID", "Region"])
        idx.register_table("Products", ["ProductID", "Category"])
        idx.register_table("Regions", ["Region", "Country"])

        assert idx.get_associated_tables("Sales") == {"Products", "Regions"}
        assert idx.get_associated_tables("Products") == {"Sales"}

    def test_get_linking_fields(self):
        idx = AssociationIndex()
        idx.register_table("Sales", ["ProductID", "Region"])
        idx.register_table("Products", ["ProductID", "Type"])
        assert idx.get_linking_fields("Sales", "Products") == ["ProductID"]

    def test_get_association_path_direct(self):
        idx = AssociationIndex()
        idx.register_table("A", ["x"])
        idx.register_table("B", ["x"])
        path = idx.get_association_path("A", "B")
        assert path == ["A", "B"]

    def test_get_association_path_through_intermediate(self):
        idx = AssociationIndex()
        idx.register_table("Products", ["ProductID", "Category"])
        idx.register_table("Sales", ["ProductID", "Region"])
        idx.register_table("Regions", ["Region", "Country"])
        # Products → Sales → Regions
        path = idx.get_association_path("Products", "Regions")
        assert path == ["Products", "Sales", "Regions"]

    def test_get_association_path_no_connection(self):
        idx = AssociationIndex()
        idx.register_table("A", ["x"])
        idx.register_table("B", ["y"])
        assert idx.get_association_path("A", "B") is None

    def test_get_association_path_same_table(self):
        idx = AssociationIndex()
        idx.register_table("A", ["x"])
        assert idx.get_association_path("A", "A") == ["A"]

    def test_table_count_and_link_count(self):
        idx = AssociationIndex()
        idx.register_table("A", ["x", "y"])
        idx.register_table("B", ["x", "z"])
        idx.register_table("C", ["y", "z"])
        assert idx.table_count == 3
        # A↔B via x, A↔C via y, B↔C via z
        assert idx.link_count == 3

    def test_association_link_involves(self):
        link = AssociationLink("Sales", "Products", "ProductID")
        assert link.involves("Sales")
        assert link.involves("Products")
        assert not link.involves("Regions")

    def test_association_link_other_table(self):
        link = AssociationLink("Sales", "Products", "ProductID")
        assert link.other_table("Sales") == "Products"
        assert link.other_table("Products") == "Sales"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SelectionEngine
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestSelectionEngine:
    """SelectionEngine: green/amber/gray propagation."""

    @pytest.fixture
    def sales_products_engine(self):
        """Two linked tables: Sales ↔ Products via ProductID."""
        ds = DataSpace("test")
        ds.load_table("Sales", [
            {"ProductID": "A1", "Region": "LATAM", "Revenue": 1500},
            {"ProductID": "B2", "Region": "EMEA",  "Revenue": 3200},
            {"ProductID": "A1", "Region": "APAC",  "Revenue": 900},
            {"ProductID": "C3", "Region": "LATAM", "Revenue": 2100},
        ])
        ds.load_table("Products", [
            {"ProductID": "A1", "Category": "Software", "Price": 99},
            {"ProductID": "B2", "Category": "Hardware", "Price": 299},
            {"ProductID": "C3", "Category": "Software", "Price": 149},
        ])
        return ds

    def test_select_marks_selected_values(self, sales_products_engine):
        ds = sales_products_engine
        ds.select("Sales", "Region", ["LATAM"])

        state = ds.get_selection_state("Sales", "Region")
        assert state["LATAM"] == SelectionState.SELECTED
        assert state["EMEA"] == SelectionState.EXCLUDED
        assert state["APAC"] == SelectionState.EXCLUDED

    def test_select_marks_associated_in_same_table(self, sales_products_engine):
        ds = sales_products_engine
        ds.select("Sales", "Region", ["LATAM"])

        # LATAM rows are 0 and 3 → ProductIDs are A1 and C3
        state = ds.get_selection_state("Sales", "ProductID")
        assert state["A1"] == SelectionState.ASSOCIATED
        assert state["C3"] == SelectionState.ASSOCIATED
        assert state["B2"] == SelectionState.EXCLUDED

    def test_select_propagates_to_linked_table(self, sales_products_engine):
        ds = sales_products_engine
        ds.select("Sales", "Region", ["LATAM"])

        # LATAM → ProductIDs A1, C3 → Products table
        state = ds.get_selection_state("Products", "Category")
        # A1=Software, C3=Software → Software is ASSOCIATED
        assert state["Software"] == SelectionState.ASSOCIATED
        # B2=Hardware → not in LATAM rows → EXCLUDED
        assert state["Hardware"] == SelectionState.EXCLUDED

    def test_select_propagates_product_prices(self, sales_products_engine):
        ds = sales_products_engine
        ds.select("Sales", "Region", ["LATAM"])

        state = ds.get_selection_state("Products", "Price")
        # A1→99, C3→149 are associated; B2→299 is excluded
        assert state[99] == SelectionState.ASSOCIATED
        assert state[149] == SelectionState.ASSOCIATED
        assert state[299] == SelectionState.EXCLUDED

    def test_get_possible_values(self, sales_products_engine):
        ds = sales_products_engine
        ds.select("Sales", "Region", ["LATAM"])
        possible = ds.get_possible("Products", "Category")
        assert possible == {"Software"}

    def test_get_excluded_values(self, sales_products_engine):
        ds = sales_products_engine
        ds.select("Sales", "Region", ["LATAM"])
        excluded = ds.get_excluded("Products", "Category")
        assert excluded == {"Hardware"}

    def test_clear_selections(self, sales_products_engine):
        ds = sales_products_engine
        ds.select("Sales", "Region", ["LATAM"])
        ds.clear_selections()
        # After clearing, no states should be cached
        state = ds.get_selection_state("Sales", "Region")
        assert state == {}

    def test_select_unknown_table_raises(self, sales_products_engine):
        ds = sales_products_engine
        with pytest.raises(KeyError, match="not found"):
            ds.select("Unknown", "Region", ["LATAM"])

    def test_select_unknown_column_raises(self, sales_products_engine):
        ds = sales_products_engine
        with pytest.raises(KeyError, match="not found"):
            ds.select("Sales", "NonExistent", ["LATAM"])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  DataSpace (Integration)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestDataSpace:
    """DataSpace: end-to-end integration tests."""

    @pytest.fixture
    def sales_ds(self):
        ds = DataSpace("SalesAnalysis")
        ds.load_table("Sales", [
            {"ProductID": "A1", "Region": "LATAM", "Revenue": 1500},
            {"ProductID": "B2", "Region": "EMEA",  "Revenue": 3200},
            {"ProductID": "A1", "Region": "APAC",  "Revenue": 900},
            {"ProductID": "C3", "Region": "LATAM", "Revenue": 2100},
            {"ProductID": "B2", "Region": "LATAM", "Revenue": 1800},
        ])
        ds.load_table("Products", [
            {"ProductID": "A1", "Category": "Software", "Price": 99},
            {"ProductID": "B2", "Category": "Hardware", "Price": 299},
            {"ProductID": "C3", "Category": "Software", "Price": 149},
        ])
        return ds

    def test_load_table(self, sales_ds):
        assert "Sales" in sales_ds.table_names
        assert "Products" in sales_ds.table_names
        assert sales_ds.row_count("Sales") == 5
        assert sales_ds.row_count("Products") == 3

    def test_auto_association(self, sales_ds):
        links = sales_ds.associations.all_links()
        assert len(links) == 1
        assert links[0].field_name == "ProductID"

    def test_get_columns(self, sales_ds):
        cols = sales_ds.get_columns("Sales")
        assert set(cols) == {"ProductID", "Region", "Revenue"}

    def test_aggregate_sum_no_selection(self, sales_ds):
        total = sales_ds.aggregate("Sales", "Revenue", "sum")
        assert total == 1500 + 3200 + 900 + 2100 + 1800

    def test_aggregate_sum_with_selection(self, sales_ds):
        sales_ds.select("Sales", "Region", ["LATAM"])
        total = sales_ds.aggregate("Sales", "Revenue", "sum")
        # LATAM rows: 1500 + 2100 + 1800 = 5400
        assert total == 5400

    def test_aggregate_count(self, sales_ds):
        sales_ds.select("Sales", "Region", ["LATAM"])
        count = sales_ds.aggregate("Sales", "Revenue", "count")
        assert count == 3

    def test_aggregate_avg(self, sales_ds):
        sales_ds.select("Sales", "Region", ["LATAM"])
        avg = sales_ds.aggregate("Sales", "Revenue", "avg")
        assert avg == 1800.0  # (1500+2100+1800)/3

    def test_aggregate_grouped(self, sales_ds):
        result = sales_ds.aggregate(
            "Sales", "Revenue", "sum", group_by=["Region"]
        )
        assert result[("LATAM",)] == 1500 + 2100 + 1800
        assert result[("EMEA",)] == 3200
        assert result[("APAC",)] == 900

    def test_aggregate_invalid_func_raises(self, sales_ds):
        with pytest.raises(ValueError, match="Unknown aggregate"):
            sales_ds.aggregate("Sales", "Revenue", "invalid_func")

    def test_explore_no_selection(self, sales_ds):
        rows = sales_ds.explore("Sales")
        assert len(rows) == 5
        assert rows[0]["Region"] in ("LATAM", "EMEA", "APAC")

    def test_explore_with_selection(self, sales_ds):
        sales_ds.select("Sales", "Region", ["EMEA"])
        rows = sales_ds.explore("Sales")
        assert len(rows) == 1
        assert rows[0]["Region"] == "EMEA"
        assert rows[0]["Revenue"] == 3200

    def test_explore_with_limit(self, sales_ds):
        rows = sales_ds.explore("Sales", limit=2)
        assert len(rows) == 2

    def test_stats(self, sales_ds):
        stats = sales_ds.stats
        assert stats["name"] == "SalesAnalysis"
        assert stats["total_tables"] == 2
        assert stats["total_associations"] == 1
        assert "Sales" in stats["tables"]
        assert "Products" in stats["tables"]

    def test_clear_selections(self, sales_ds):
        sales_ds.select("Sales", "Region", ["LATAM"])
        sales_ds.clear_selections()
        # After clear, aggregate should include all rows
        total = sales_ds.aggregate("Sales", "Revenue", "sum")
        assert total == 1500 + 3200 + 900 + 2100 + 1800

    def test_three_table_chain(self):
        """Test propagation across Products → Sales → Regions."""
        ds = DataSpace("Chain")
        ds.load_table("Sales", [
            {"ProductID": "A1", "RegionCode": "R1", "Revenue": 100},
            {"ProductID": "A1", "RegionCode": "R2", "Revenue": 200},
            {"ProductID": "B2", "RegionCode": "R1", "Revenue": 300},
        ])
        ds.load_table("Products", [
            {"ProductID": "A1", "Name": "Widget"},
            {"ProductID": "B2", "Name": "Gadget"},
        ])
        ds.load_table("Regions", [
            {"RegionCode": "R1", "Country": "Mexico"},
            {"RegionCode": "R2", "Country": "Colombia"},
        ])
        # Select Product "Widget" (A1)
        ds.select("Products", "Name", ["Widget"])

        # Propagation: Widget → A1 → Sales rows 0,1 → RegionCodes R1,R2
        regions_state = ds.get_selection_state("Regions", "Country")
        assert regions_state["Mexico"] == SelectionState.ASSOCIATED
        assert regions_state["Colombia"] == SelectionState.ASSOCIATED

    def test_empty_table(self):
        ds = DataSpace("empty")
        ds.load_table("Empty", [])
        assert ds.row_count("Empty") == 0

    def test_get_column(self, sales_ds):
        col = sales_ds.get_column("Sales", "Revenue")
        assert col.row_count == 5

    def test_get_column_invalid_table_raises(self, sales_ds):
        with pytest.raises(KeyError):
            sales_ds.get_column("Nonexistent", "x")

    def test_get_column_invalid_column_raises(self, sales_ds):
        with pytest.raises(KeyError):
            sales_ds.get_column("Sales", "Nonexistent")
