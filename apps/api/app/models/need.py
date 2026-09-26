from geoalchemy2 import Geometry
from sqlalchemy import Float, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Cell(Base):
    """One H3 hexagon (see app.geo). Need is computed per Cell; features live elsewhere."""

    __tablename__ = "cells"

    h3_index: Mapped[str] = mapped_column(String(15), primary_key=True)
    resolution: Mapped[int] = mapped_column(SmallInteger)
    center_lat: Mapped[float] = mapped_column(Float)
    center_lng: Mapped[float] = mapped_column(Float)
    # GIST-indexed (geoalchemy2 creates the index) for viewport and spatial joins.
    geometry: Mapped[str] = mapped_column(Geometry("POLYGON", srid=4326), nullable=False)
