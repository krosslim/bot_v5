from pydantic import BaseModel, ConfigDict

class OfficeCapacityDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True,
                              frozen=True)

    weekday: int
    short_name: str
    capacity: int



