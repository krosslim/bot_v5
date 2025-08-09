from pydantic import BaseModel, ConfigDict

class OfficeCapacityDTO(BaseModel):
    weekday: int
    short_name: str
    capacity: int

    model_config = ConfigDict(from_attributes=True,
                              frozen=True)