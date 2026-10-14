import cv2
import logging

from http import HTTPStatus
from urllib.parse import urljoin

from people_gator.core.connector import Connector
from people_gator.core.layout import PeopleGatorFaceRegionLayout


logger = logging.getLogger(__name__)


class DatabaseApiService:
    def __init__(self, config):
        self.api_url = config.get("api_url")
        self.username = config.get("username")
        self.password = config.get("password")

        self.connector = Connector(username=self.username,
                                   password=self.password,
                                   login_route=f"{self.api_url}/token/login",
                                   refresh_route=f"{self.api_url}/token/refresh",
                                   scopes=["people-gator:browse",
                                           "people-gator:annotate",
                                           "people-gator:ingest",
                                           "people-gator:admin"])

    def compose_url(self, *args):
        args = [str(arg).strip("/") for arg in args]
        route = "/".join(args)
        return urljoin(self.api_url, route)

    def search_entities(self, query, route="/api/v1/search-entities", response_model=None):
        url = self.compose_url(route)
        params = {"query.text": query}
        response = self.connector.get(url, params=params)

        if response.status_code != HTTPStatus.OK:
            return None

        result = response.json()
        if response_model:
            try:
                result = response_model(**result)
            except Exception as e:
                logger.error(f"Error parsing response into model {response_model}: {e}")
                return None

        return result

    def create_entity(self, name, route="/api/v1/entities", response_model=None):
        url = self.compose_url(route)
        payload = {
            'entity_type': 'person',
            'name': name,
            'description': '',
            'short_description': '',
            'aliases': [],
            'wikidata_id': '',
            'nlcr_authority_id': ''
        }

        response = self.connector.post(url, json=payload)

        if response.status_code != HTTPStatus.CREATED:
            return None

        result = response.json()
        if response_model:
            try:
                result = response_model(**result)
            except Exception as e:
                logger.error(f"Error parsing response into model {response_model}: {e}")
                return None

        return result

    def create_document(self, document_id, document_name, library, route="/api/v1/documents", response_model=None):
        url = self.compose_url(route)
        payload = {
            "library": library,
            "document_id": str(document_id),
            "name": document_name,
        }

        response = self.connector.post(url, json=payload)

        if response.status_code != HTTPStatus.CREATED:
            return None

        result = response.json()
        if response_model:
            try:
                result = response_model(**result)
            except Exception as e:
                logger.error(f"Error parsing response into model {response_model}: {e}")
                return None

        return result

    def create_page(self, page_id, document_id, library, route="/api/v1/pages", response_model=None):
        url = self.compose_url(route)
        payload = {
            "library": library,
            "document_id": str(document_id),
            "page_id": str(page_id),
        }

        response = self.connector.post(url, json=payload)

        if response.status_code != HTTPStatus.CREATED:
            return None

        result = response.json()
        if response_model:
            try:
                result = response_model(**result)
            except Exception as e:
                logger.error(f"Error parsing response into model {response_model}: {e}")
                return None

        return result

    def create_face(self, face_region: PeopleGatorFaceRegionLayout, source_id, route="/api/v1/faces", response_model=None):
        url = self.compose_url(route)

        face_x_min, face_y_min, face_x_max, face_y_max = face_region.get_polygon_bounding_box()
        face_width = face_x_max - face_x_min
        face_height = face_y_max - face_y_min

        payload = {
            "source_id": source_id,

            "identifier": face_region.id,
            "bounding_box": {
                "x": face_x_min,
                "y": face_y_min,
                "width": face_width,
                "height": face_height,
            },
            "keypoints": [
                {
                  "type": "left_eye",
                  "x": face_region.face_metadata.left_eye_position.x,
                  "y": face_region.face_metadata.left_eye_position.y
                },
                {
                  "type": "right_eye",
                  "x": face_region.face_metadata.right_eye_position.x,
                  "y": face_region.face_metadata.right_eye_position.y
                },
                {
                  "type": "nose",
                  "x": face_region.face_metadata.nose_position.x,
                  "y": face_region.face_metadata.nose_position.y
                },
                {
                  "type": "left_mouth_corner",
                  "x": face_region.face_metadata.left_mouth_corner_position.x,
                  "y": face_region.face_metadata.left_mouth_corner_position.y
                },
                {
                  "type": "right_mouth_corner",
                  "x": face_region.face_metadata.right_mouth_corner_position.x,
                  "y": face_region.face_metadata.right_mouth_corner_position.y
                }
              ],
            "confidence": 1,
            "embeddings": [
                {
                    "model_identifier": "vit_small_patch8_gap_112.cosface_ms1mv3",
                    "vector": [0] * 512
                }
            ],
        }

        if face_region.face_metadata.page_identity.identity.peoplegator_id is not None:
            payload["entity_id"] = face_region.face_metadata.page_identity.identity.peoplegator_id
            payload["entity_link_state"] = "automatic"

        response = self.connector.post(url, json=payload)

        if response.status_code != HTTPStatus.CREATED:
            return None

        result = response.json()
        if response_model:
            try:
                result = response_model(**result)
            except Exception as e:
                logger.error(f"Error parsing response into model {response_model}: {e}")
                return None

        return result

    def put_page_image(self, page_image, page_id, route="/api/v1/pages/{page_id}/image", response_model=None):
        url = self.compose_url(route.format(page_id=page_id))

        encoded_image = cv2.imencode('.jpg', page_image)[1].tobytes()

        files = {
            "file": (f"{page_id}.jpg", encoded_image, "image/jpeg")
        }

        response = self.connector.put(url, files=files)

        if response.status_code != HTTPStatus.OK:
            return None

        result = response.json()
        if response_model:
            try:
                result = response_model(**result)
            except Exception as e:
                logger.error(f"Error parsing response into model {response_model}: {e}")
                return None

        return result

    def put_page_layout(self, page_layout_dict, page_id, route="/api/v1/pages/{page_id}/page-layout", response_model=None):
        url = self.compose_url(route.format(page_id=page_id))

        response = self.connector.put(url, json=page_layout_dict)

        if response.status_code != HTTPStatus.OK:
            return None

        result = response.json()
        if response_model:
            try:
                result = response_model(**result)
            except Exception as e:
                logger.error(f"Error parsing response into model {response_model}: {e}")
                return None

        return result

    def get_document_info(self, document_id, library, route="/api/v1/documents/lookup", response_model=None):
        url = self.compose_url(route)
        params = {
            "library": library,
            "document_id": str(document_id),
        }

        response = self.connector.get(url, params=params)

        if response.status_code != HTTPStatus.OK:
            return None

        result = response.json()
        if response_model:
            try:
                result = response_model(**result)
            except Exception as e:
                logger.error(f"Error parsing response into model {response_model}: {e}")
                return None

        return result

    def get_page_info(self, document_id, page_id, library, route="/api/v1/pages/lookup", response_model=None):
        url = self.compose_url(route)
        params = {
            "library": library,
            "document_id": str(document_id),
            "page_id": str(page_id),
        }

        response = self.connector.get(url, params=params)

        if response.status_code != HTTPStatus.OK:
            return None

        result = response.json()
        if response_model:
            try:
                result = response_model(**result)
            except Exception as e:
                logger.error(f"Error parsing response into model {response_model}: {e}")
                return None

        return result

    def get_faces_for_page(self, source_id, route="/api/v1/faces", response_model=None):
        url = self.compose_url(route)
        params = {
            "filter.source_id": str(source_id),
            "limit": 1_000_000,
        }

        response = self.connector.get(url, params=params)

        if response.status_code != HTTPStatus.OK:
            return None

        result = response.json()
        if response_model:
            try:
                result = [response_model(**item) for item in result]
            except Exception as e:
                logger.error(f"Error parsing response into model {response_model}: {e}")
                return None

        return result

    def get_entity_info(self, entity_id, route="/api/v1/entities/{entity_id}", response_model=None):
        url = self.compose_url(route.format(entity_id=entity_id))

        response = self.connector.get(url)

        if response.status_code != HTTPStatus.OK:
            return None

        result = response.json()
        if response_model:
            try:
                result = response_model(**result)
            except Exception as e:
                logger.error(f"Error parsing response into model {response_model}: {e}")
                return None

        return result
