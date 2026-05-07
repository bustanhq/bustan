from $package_name.app_service import AppService


def test_get_message_returns_expected_payload() -> None:
    service = AppService()
    result = service.get_message()
    assert result == {"message": "Hello from $project_name"}
