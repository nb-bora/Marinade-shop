from typing import Iterable
import uuid

from sqlalchemy.orm import Session

from app.models.operator import MobileOperatorPrefix
from app.schemas.operator import MobileOperatorPrefixCreate, MobileOperatorPrefixUpdate
from app.utils.phone import MobileOperator


class OperatorService:
    def __init__(self, db: Session):
        self.db = db

    def list_prefixes(
        self, country_code: str = "+237", include_inactive: bool = False
    ) -> list[MobileOperatorPrefix]:
        query = self.db.query(MobileOperatorPrefix).filter(
            MobileOperatorPrefix.country_code == country_code
        )
        if not include_inactive:
            query = query.filter(MobileOperatorPrefix.is_active == True)
        return query.order_by(MobileOperatorPrefix.national_prefix).all()

    def create_prefix(self, data: MobileOperatorPrefixCreate) -> MobileOperatorPrefix:
        existing = (
            self.db.query(MobileOperatorPrefix)
            .filter(
                MobileOperatorPrefix.country_code == data.country_code,
                MobileOperatorPrefix.national_prefix == data.national_prefix,
            )
            .first()
        )
        if existing:
            raise ValueError("This national prefix is already registered")
        prefix = MobileOperatorPrefix(**data.model_dump())
        self.db.add(prefix)
        self.db.flush()
        self.db.refresh(prefix)
        return prefix

    def update_prefix(
        self, prefix_id: uuid.UUID, data: MobileOperatorPrefixUpdate
    ) -> MobileOperatorPrefix | None:
        prefix = self.db.get(MobileOperatorPrefix, prefix_id)
        if not prefix:
            return None
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(prefix, field, value)
        self.db.flush()
        return prefix

    def active_operators(self, country_code: str = "+237") -> list[MobileOperator]:
        grouped: dict[str, dict[str, object]] = {}
        for row in self.list_prefixes(country_code):
            item = grouped.setdefault(
                row.operator_code,
                {"code": row.operator_code, "name": row.operator_name, "prefixes": []},
            )
            item["prefixes"].append(row.national_prefix)  # type: ignore[union-attr]
        return [
            MobileOperator(
                code=str(item["code"]),
                name=str(item["name"]),
                prefixes=tuple(sorted(item["prefixes"], key=len, reverse=True)),
            )
            for item in grouped.values()
        ]  # type: ignore[arg-type]

    def normalize_mobile(self, raw: str) -> tuple[str, MobileOperator]:
        from app.utils.phone import normalize_cameroon_mobile

        return normalize_cameroon_mobile(raw, self.active_operators())
