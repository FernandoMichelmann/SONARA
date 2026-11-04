from datetime import date
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class UserRegister(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=10, max_length=128)
    address: str = Field(min_length=5, max_length=240)
    birth_date: date
    cpf: str = Field(min_length=11, max_length=11)

    @field_validator("full_name", "address")
    @classmethod
    def trim_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("cpf")
    @classmethod
    def validate_cpf(cls, value: str) -> str:
        cpf = "".join(char for char in value if char.isdigit())
        if len(cpf) != 11 or len(set(cpf)) == 1:
            raise ValueError("CPF inválido.")
        total = sum(int(cpf[index]) * (10 - index) for index in range(9))
        digit = (total * 10) % 11
        digit = 0 if digit == 10 else digit
        if digit != int(cpf[9]):
            raise ValueError("CPF inválido.")
        total = sum(int(cpf[index]) * (11 - index) for index in range(10))
        digit = (total * 10) % 11
        digit = 0 if digit == 10 else digit
        if digit != int(cpf[10]):
            raise ValueError("CPF inválido.")
        return cpf


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: EmailStr
    full_name: str
    role: str
    is_active: bool
