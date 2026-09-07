class FaceMetadata:
    def to_dict(self):
        return {}

    @classmethod
    def from_dict(cls, data: dict, page_layout=None):
        return cls()
