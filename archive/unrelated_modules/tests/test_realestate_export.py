"""Tests for the Real Estate Export/Import module."""

from __future__ import annotations

from realestate.export_import import (
    export_to_csv,
    export_to_json,
    import_properties,
    parse_csv_import,
)


class TestExportJSON:
    def test_export_json_empty(self):
        result = export_to_json([])
        assert '"total_properties": 0' in result
        assert '"properties": []' in result

    def test_export_json_with_properties(self):
        from realestate.application.dto import PropertyDTO
        props = [
            PropertyDTO(
                property_id="RE-001", title="Test Property",
                price=5000000, city="Mumbai", locality="Bandra",
                bedrooms=2, bathrooms=2, carpet_area_sqft=900,
                furnishing="furnished", is_verified=True,
                amenities=["Pool", "Gym"],
            ),
        ]
        result = export_to_json(props)
        assert '"total_properties": 1' in result
        assert '"RE-001"' in result
        assert '"Mumbai"' in result
        assert '"furnished"' in result

    def test_export_json_includes_metadata(self):
        from realestate.application.dto import PropertyDTO
        result = export_to_json([PropertyDTO(property_id="RE-001", title="T")])
        assert "exported_at" in result
        assert "exported_at_formatted" in result


class TestExportCSV:
    def test_export_csv_empty(self):
        result = export_to_csv([])
        assert "Property ID" in result
        assert "Title" in result

    def test_export_csv_with_properties(self):
        from realestate.application.dto import PropertyDTO
        props = [
            PropertyDTO(
                property_id="RE-001", title="Test Flat",
                price=7500000, city="Bangalore", locality="Whitefield",
                bedrooms=3, bathrooms=3, carpet_area_sqft=1200,
                furnishing="semi_furnished", is_verified=True,
                amenities=["Swimming Pool", "Gym"],
            ),
        ]
        result = export_to_csv(props)
        assert "RE-001" in result
        assert "Test Flat" in result
        assert "Whitefield" in result
        assert "Yes" in result  # is_verified

    def test_export_csv_bom(self):
        """CSV export should include BOM for Excel compatibility."""
        result = export_to_csv([])
        assert result.startswith("\ufeff")

    def test_export_csv_headers(self):
        from realestate.application.dto import PropertyDTO
        result = export_to_csv([PropertyDTO(property_id="R1", title="T")])
        assert "Price (INR)" in result
        assert "Carpet Area (sq.ft)" in result
        assert "Property Type" in result


class TestCSVParse:
    def test_parse_basic_csv(self):
        csv_content = "Title,City,Price (INR),Bedrooms\nTest Flat,Mumbai,5000000,2\n"
        props, errors = parse_csv_import(csv_content)
        assert len(props) == 1
        assert props[0]["title"] == "Test Flat"
        assert props[0]["city"] == "Mumbai"
        assert props[0]["price"] == 5000000.0

    def test_parse_with_all_fields(self):
        csv_content = (
            "Title,City,Price (INR),Bedrooms,Carpet Area (sq.ft),Furnishing,Property Type,Latitude,Longitude\n"
            "Luxury Villa,Bangalore,12000000,4,2500,Furnished,Villa,12.9716,77.5946\n"
        )
        props, errors = parse_csv_import(csv_content)
        assert len(props) == 1
        assert props[0]["bedrooms"] == 4
        assert props[0]["carpet_area_sqft"] == 2500.0
        assert props[0]["furnishing"] == "furnished"
        assert props[0]["latitude"] == 12.9716

    def test_parse_empty_returns_no_properties(self):
        csv_content = "Title,City,Price (INR)\n"
        props, errors = parse_csv_import(csv_content)
        assert len(props) == 0

    def test_parse_rupee_symbol(self):
        """Handle ₹ prefix in price column."""
        csv_content = "Title,City,Price (INR)\nTest,Delhi,₹7500000\n"
        props, errors = parse_csv_import(csv_content)
        assert len(props) == 1
        assert props[0]["price"] == 7500000.0

    def test_parse_price_with_commas(self):
        csv_content = "Title,City,Price (INR)\nTest,Delhi,\"1,25,00,000\"\n"
        props, errors = parse_csv_import(csv_content)
        assert len(props) == 1
        assert props[0]["price"] == 12500000.0

    def test_parse_missing_title_or_city(self):
        csv_content = "Title,City,Price\n,Dubai,1000000\nTest,,2000000\n"
        props, errors = parse_csv_import(csv_content)
        assert len(props) == 0  # Both rows missing required fields


class TestImportProperties:
    def test_import_into_service(self):
        from realestate.application.services import PropertyService
        svc = PropertyService()
        data = [
            {"title": "Imported 1", "property_type": "apartment", "price": 5000000,
             "city": "Mumbai", "owner_id": "import"},
            {"title": "Imported 2", "property_type": "villa", "price": 12000000,
             "city": "Bangalore", "owner_id": "import", "bedrooms": 4},
        ]
        created, errors = import_properties(data, svc)
        assert created == 2
        assert len(errors) == 0
        assert len(svc.list_all()) == 2

    def test_import_empty_list(self):
        from realestate.application.services import PropertyService
        created, errors = import_properties([], PropertyService())
        assert created == 0
        assert len(errors) == 0


class TestExportImportFlow:
    """End-to-end: Export → re-import cycle."""

    def test_export_import_cycle(self):
        """Export → Parse CSV → Create properties → Verify."""
        from realestate.application.services import PropertyService

        svc = PropertyService()

        # Create a source property
        svc.create_property(
            title="Export Test", description="", property_type="apartment",
            price=7500000, city="Delhi", locality="Dwarka",
            owner_id="test", bedrooms=3,
        )

        # Export to CSV
        props = svc.list_all()
        csv_data = export_to_csv(props)

        # Parse back
        parsed, errors = parse_csv_import(csv_data)
        assert len(parsed) >= 1
        assert "Delhi" in str(parsed)

        # Import into a fresh service
        svc2 = PropertyService()
        created, import_errors = import_properties(parsed, svc2)
        assert created >= 1
        assert len(svc2.list_all()) >= 1
