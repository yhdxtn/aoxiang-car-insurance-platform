from datetime import date
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Vehicle(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    plateNo: str = Field(default="", max_length=20)
    vin: str = Field(default="", max_length=32)
    engineNo: str = Field(default="", max_length=64)
    brandModel: str = Field(default="", max_length=160)
    registerDate: str = Field(default="", max_length=10)
    issueDate: str = Field(default="", max_length=10)
    ownerName: str = Field(default="", max_length=100)
    idNumber: str = Field(default="", max_length=32)
    address: str = Field(default="", max_length=500)
    phone: str = Field(default="", max_length=20)
    vehicleType: str = Field(default="", max_length=32)
    useNature: str = Field(default="", max_length=60)
    seatCount: int = Field(default=0, ge=0, le=100)
    selectedModelCode: str | None = Field(default=None, max_length=200)

    @field_validator("registerDate", "issueDate")
    @classmethod
    def actual_date(cls, value):
        if value:
            date.fromisoformat(value)
        return value


class QuoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requestId: str = Field(min_length=8, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")
    vehicleType: Literal["CAR", "TRUCK", "MOTORCYCLE"]
    vehicle: Vehicle
    plan: Literal["COMPULSORY", "STANDARD", "FULL"] = "STANDARD"
    thirdPartyAmount: str = "2000000"
    driverAmount: str = "10000"
    passengerAmount: str = "10000"
    medicalAmount: str = "200000"

    @field_validator("thirdPartyAmount", "driverAmount", "passengerAmount", "medicalAmount")
    @classmethod
    def whole_yuan(cls, value):
        amount = Decimal(value)
        if not amount.is_finite() or amount < 0 or amount > 100_000_000 or amount != amount.to_integral_value():
            raise ValueError("保额必须是有效的非负整数人民币元")
        return str(int(amount))


class OcrRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    imageBase64: str = Field(min_length=4, max_length=14_000_000)
    mimeType: Literal["image/jpeg", "image/png", "image/webp"]
    documentType: Literal["DRIVING_LICENSE", "ID_CARD", "OTHER"]
