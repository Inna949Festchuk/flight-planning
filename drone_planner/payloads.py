"""Модель ПН из ТТХ."""

from dataclasses import dataclass


@dataclass
class Payload:
    uav: str
    pn_type: str
    pn_name: str
    ly: float
    lx: float
    f: float
    Ny: int
    Nx: int
    r: float

    def height_for_gsd(self, gsd_cm: float) -> float:
        """Высота (м) из GSD (см/пиксель)."""
        return (gsd_cm * 10 * self.f) / self.r

    def gsd_for_height(self, H_m: float) -> float:
        """GSD (см/пиксель) на высоте H (м)."""
        return (H_m * self.r) / (self.f * 10)

    def frame_size(self, H_m: float):
        """Размер кадра на земле (м). (W_x, W_y)."""
        W_x = (self.lx * H_m) / self.f
        W_y = (self.ly * H_m) / self.f
        return W_x, W_y

    def line_spacing(self, gsd_cm: float, overlap_x: float) -> float:
        """Шаг между галсами (м)."""
        H = self.height_for_gsd(gsd_cm)
        W_x, _ = self.frame_size(H)
        return W_x * (1 - overlap_x / 100)

    def shot_spacing(self, gsd_cm: float, overlap_y: float) -> float:
        """Шаг между снимками (м)."""
        H = self.height_for_gsd(gsd_cm)
        _, W_y = self.frame_size(H)
        return W_y * (1 - overlap_y / 100)


PAYLOADS = {
    # Genimi
    "Geoscan PF1B": Payload("Genimi", "Видимого диапазона", "Geoscan PF1B",
                            23.5, 15.6, 20, 6000, 4000, 3.9),
    "Geoscan Pollux": Payload("Genimi", "Мультиспектральная", "Geoscan Pollux",
                              4.968, 3.726, 8, 1440, 1080, 3.45),
    # Геоскан 201
    "Riebo R4": Payload("Геоскан 201", "Видимого диапазона", "Riebo R4",
                        36, 24, 40, 8192, 5464, 4.4),
    "Riebo R6": Payload("Геоскан 201", "Видимого диапазона", "Riebo R6",
                        35.7, 23.8, 18, 9504, 6336, 3.76),
    "DSC-RX1RM2": Payload("Геоскан 201", "Видимого диапазона", "DSC-RX1RM2",
                          35.9, 24, 35, 7978, 5333, 4.5),
    "DSC-RX1RM3": Payload("Геоскан 201", "Видимого диапазона", "DSC-RX1RM3",
                          35.9, 24, 35, 9548, 6383, 3.76),
    "Sony ZV-E10": Payload("Геоскан 201", "Видимого диапазона", "Sony ZV-E10",
                           23.5, 15.6, 16, 6000, 4000, 3.92),
    "Geoscan Pollux (201)": Payload("Геоскан 201", "Мультиспектральная",
                                    "Geoscan Pollux",
                                    4.968, 3.726, 8, 1440, 1080, 3.45),
    # Геоскан 801
    "Узкоугольная": Payload("Геоскан 801", "Видимого диапазона", "Узкоугольная",
                            6.17, 4.55, 16, 4000, 3000, 1.54),
    "Широкоугольная": Payload("Геоскан 801", "Видимого диапазона", "Широкоугольная",
                              6.17, 4.55, 4.35, 4000, 3000, 1.54),
    "Тепловизор": Payload("Геоскан 801", "Тепловизионная", "Тепловизор",
                          7.68, 6.14, 9.1, 640, 512, 12),
}


SURVEY_ORDER = ("visible", "multispectral", "thermal")

SURVEY_PN = {
    "visible": "Видимого диапазона",
    "multispectral": "Мультиспектральная",
    "thermal": "Тепловизионная",
}


def payload_for_survey(uav_name: str, survey_type: str):
    """Первая камера этого борта, которая снимает нужный тип района."""
    pn_type = SURVEY_PN.get(survey_type)
    if pn_type is None:
        return None
    for payload in PAYLOADS.values():
        if payload.uav == uav_name and payload.pn_type == pn_type:
            return payload
    return None


def survey_type_of_payload(payload) -> str:
    for survey_type, pn_type in SURVEY_PN.items():
        if payload.pn_type == pn_type:
            return survey_type
    return "visible"


def payload_from_unit_name(unit_name: str):
    """Камера из имени борта: в нём есть название ПН."""
    matches = [payload for payload in PAYLOADS.values()
               if payload.pn_name and payload.pn_name in unit_name
               and payload.uav in unit_name]
    if not matches:
        return None
    return max(matches, key=lambda payload: len(payload.pn_name))


def gsd_cm_from_m(gsd_m: float) -> float:
    """GSD из м/пиксель в см/пиксель, как ждут формулы высоты и шага галсов."""
    return gsd_m * 100.0


def default_payload(uav_name: str) -> Payload:
    """Первая ПН видимого диапазона для указанного БВС."""
    for p in PAYLOADS.values():
        if p.uav == uav_name and p.pn_type == "Видимого диапазона":
            return p
    raise ValueError(f"Нет видимой ПН для {uav_name}")