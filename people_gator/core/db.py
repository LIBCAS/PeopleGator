import cv2
import logging

from http import HTTPStatus
from urllib.parse import urljoin

from people_gator.core.connector import Connector
from people_gator.core.layout import PeopleGatorFaceRegionLayout


logger = logging.getLogger(__name__)


class DatabaseApiService:
    """PeopleGatorApp client for documents, pages, faces, and person entities."""

    def __init__(self, config):
        """Initialize DatabaseApiService from the supplied settings and data.

        Args:
            config: INI configuration or engine section for this component.

        Raises:
            AuthenticationError: If the initial app login fails.
        """
        logger.debug("Initializing PeopleGatorApp connection")
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
        """Join normalized route components to the configured API URL.

        Args:
            *args: Route components, stripped of surrounding slashes.

        Returns:
            The absolute app API URL.
        """
        args = [str(arg).strip("/") for arg in args]
        route = "/".join(args)
        return urljoin(self.api_url, route)

    def search_entities(self, query, route="/api/v1/search-entities", response_model=None):
        """Search entities through the PeopleGatorApp API.

        Args:
            query: Person-name search text or a sequence of unique nonblank search terms.
            route: API route template; defaults to the operation's app endpoint.
            response_model: Optional Pydantic response class; None returns decoded JSON.

        Returns:
            Decoded JSON or the requested response model; None on an unsuccessful status or model-validation failure.

        Raises:
            ValueError: If an otherwise successful response contains invalid JSON.
        """
        url = self.compose_url(route)
        if not isinstance(query, str):
            if not isinstance(query, (list, tuple)) or any(not isinstance(q, str) for q in query):
                raise ValueError("Search requires text or a sequence of text terms")
            query = list(dict.fromkeys(q.strip() for q in query if q.strip()))
            if not query:
                raise ValueError("Search requires at least one nonblank term")
        params = {"query.text": query}
        response = self.connector.get(url, params=params)

        if response.status_code != HTTPStatus.OK:
            logger.warning("Database operation search_entities failed (HTTP %s)", response.status_code)
            return None

        try:
            result = response.json()
        except ValueError:
            logger.error("Database returned invalid JSON (HTTP %s)", response.status_code)
            raise
        if response_model:
            try:
                result = response_model(**result)
            except Exception as e:
                logger.error("Database operation search_entities: invalid response model (%s)", type(e).__name__)
                return None

        return result

    def create_entity(self, name, route="/api/v1/entities", response_model=None, *,
                      aliases=None, description="", short_description=""):
        """Create entity through the PeopleGatorApp API.

        Args:
            name: Proposed person name, or None when unknown.
            route: API route template; defaults to the operation's app endpoint.
            response_model: Optional Pydantic response class; None returns decoded JSON.
            aliases: Optional source-grounded alternative names; duplicates are removed.
            description: Source-grounded long description; defaults to an empty string.
            short_description: Source-grounded brief description; defaults to an empty string.

        Returns:
            Decoded JSON or the requested response model; None on an unsuccessful status or model-validation failure.

        Raises:
            ValueError: If an otherwise successful response contains invalid JSON.
        """
        url = self.compose_url(route)
        payload = {
            'entity_type': 'person',
            'name': name,
            'description': description,
            'short_description': short_description,
            'aliases': list(dict.fromkeys(aliases or [])),
            'wikidata_id': '',
            'nlcr_authority_id': ''
        }

        response = self.connector.post(url, json=payload)

        if response.status_code != HTTPStatus.CREATED:
            logger.warning("Database operation create_entity failed (HTTP %s)", response.status_code)
            return None

        try:
            result = response.json()
        except ValueError:
            logger.error("Database returned invalid JSON (HTTP %s)", response.status_code)
            raise
        if response_model:
            try:
                result = response_model(**result)
            except Exception as e:
                logger.error("Database operation create_entity: invalid response model (%s)", type(e).__name__)
                return None

        return result

    def create_document(self, document_id, document_name, library, route="/api/v1/documents", response_model=None):
        """Create document through the PeopleGatorApp API.

        Args:
            document_id: Document identifier within the library.
            document_name: Document display name.
            library: Library identifier used for app document lookup.
            route: API route template; defaults to the operation's app endpoint.
            response_model: Optional Pydantic response class; None returns decoded JSON.

        Returns:
            Decoded JSON or the requested response model; None on an unsuccessful status or model-validation failure.

        Raises:
            ValueError: If an otherwise successful response contains invalid JSON.
        """
        url = self.compose_url(route)
        payload = {
            "library": library,
            "document_id": str(document_id),
            "name": document_name,
        }

        response = self.connector.post(url, json=payload)

        if response.status_code != HTTPStatus.CREATED:
            logger.warning("Database operation create_document failed (HTTP %s)", response.status_code)
            return None

        try:
            result = response.json()
        except ValueError:
            logger.error("Database returned invalid JSON (HTTP %s)", response.status_code)
            raise
        if response_model:
            try:
                result = response_model(**result)
            except Exception as e:
                logger.error("Database operation create_document: invalid response model (%s)", type(e).__name__)
                return None

        return result

    def create_page(self, page_id, document_id, library, route="/api/v1/pages", response_model=None):
        """Create page through the PeopleGatorApp API.

        Args:
            page_id: Page identifier (app source ID for image/layout uploads).
            document_id: Document identifier within the library.
            library: Library identifier used for app document lookup.
            route: API route template; defaults to the operation's app endpoint.
            response_model: Optional Pydantic response class; None returns decoded JSON.

        Returns:
            Decoded JSON or the requested response model; None on an unsuccessful status or model-validation failure.

        Raises:
            ValueError: If an otherwise successful response contains invalid JSON.
        """
        url = self.compose_url(route)
        payload = {
            "library": library,
            "document_id": str(document_id),
            "page_id": str(page_id),
        }

        response = self.connector.post(url, json=payload)

        if response.status_code != HTTPStatus.CREATED:
            logger.warning("Database operation create_page failed (HTTP %s)", response.status_code)
            return None

        try:
            result = response.json()
        except ValueError:
            logger.error("Database returned invalid JSON (HTTP %s)", response.status_code)
            raise
        if response_model:
            try:
                result = response_model(**result)
            except Exception as e:
                logger.error("Database operation create_page: invalid response model (%s)", type(e).__name__)
                return None

        return result

    def create_face(self, face_region: PeopleGatorFaceRegionLayout, source_id, route="/api/v1/faces", response_model=None):
        """Create face through the PeopleGatorApp API.

        Args:
            face_region: Face region to export or assign.
            source_id: App source identifier for a page or document.
            route: API route template; defaults to the operation's app endpoint.
            response_model: Optional Pydantic response class; None returns decoded JSON.

        Returns:
            Decoded JSON or the requested response model; None on an unsuccessful status or model-validation failure.

        Raises:
            ValueError: If an otherwise successful response contains invalid JSON.
        """
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
            logger.warning("Database operation create_face failed (HTTP %s)", response.status_code)
            return None

        try:
            result = response.json()
        except ValueError:
            logger.error("Database returned invalid JSON (HTTP %s)", response.status_code)
            raise
        if response_model:
            try:
                result = response_model(**result)
            except Exception as e:
                logger.error("Database operation create_face: invalid response model (%s)", type(e).__name__)
                return None

        return result

    def put_page_image(self, page_image, page_id, route="/api/v1/pages/{page_id}/image", response_model=None):
        """Put page image through the PeopleGatorApp API.

        Args:
            page_image: Page image array in page-layout coordinates.
            page_id: Page identifier (app source ID for image/layout uploads).
            route: API route template; defaults to the operation's app endpoint.
            response_model: Optional Pydantic response class; None returns decoded JSON.

        Returns:
            Decoded JSON or the requested response model; None on an unsuccessful status or model-validation failure.

        Raises:
            ValueError: If an otherwise successful response contains invalid JSON.
        """
        url = self.compose_url(route.format(page_id=page_id))

        encoded_image = cv2.imencode('.jpg', page_image)[1].tobytes()

        files = {
            "file": (f"{page_id}.jpg", encoded_image, "image/jpeg")
        }

        response = self.connector.put(url, files=files)

        if response.status_code != HTTPStatus.OK:
            logger.warning("Database operation put_page_image failed (HTTP %s)", response.status_code)
            return None

        try:
            result = response.json()
        except ValueError:
            logger.error("Database returned invalid JSON (HTTP %s)", response.status_code)
            raise
        if response_model:
            try:
                result = response_model(**result)
            except Exception as e:
                logger.error("Database operation put_page_image: invalid response model (%s)", type(e).__name__)
                return None

        return result

    def put_page_layout(self, page_layout_dict, page_id, route="/api/v1/pages/{page_id}/page-layout", response_model=None):
        """Put page layout through the PeopleGatorApp API.

        Args:
            page_layout_dict: App-compatible page-layout mapping.
            page_id: Page identifier (app source ID for image/layout uploads).
            route: API route template; defaults to the operation's app endpoint.
            response_model: Optional Pydantic response class; None returns decoded JSON.

        Returns:
            Decoded JSON or the requested response model; None on an unsuccessful status or model-validation failure.

        Raises:
            ValueError: If an otherwise successful response contains invalid JSON.
        """
        url = self.compose_url(route.format(page_id=page_id))

        response = self.connector.put(url, json=page_layout_dict)

        if response.status_code != HTTPStatus.OK:
            logger.warning("Database operation put_page_layout failed (HTTP %s)", response.status_code)
            return None

        try:
            result = response.json()
        except ValueError:
            logger.error("Database returned invalid JSON (HTTP %s)", response.status_code)
            raise
        if response_model:
            try:
                result = response_model(**result)
            except Exception as e:
                logger.error("Database operation put_page_layout: invalid response model (%s)", type(e).__name__)
                return None

        return result

    def get_document_info(self, document_id, library, route="/api/v1/documents/lookup", response_model=None):
        """Get document info through the PeopleGatorApp API.

        Args:
            document_id: Document identifier within the library.
            library: Library identifier used for app document lookup.
            route: API route template; defaults to the operation's app endpoint.
            response_model: Optional Pydantic response class; None returns decoded JSON.

        Returns:
            Decoded JSON or the requested response model; None on an unsuccessful status or model-validation failure.

        Raises:
            ValueError: If an otherwise successful response contains invalid JSON.
        """
        url = self.compose_url(route)
        params = {
            "library": library,
            "document_id": str(document_id),
        }

        response = self.connector.get(url, params=params)

        if response.status_code != HTTPStatus.OK:
            log = logger.debug if response.status_code == HTTPStatus.NOT_FOUND else logger.warning
            log("Database operation get_document_info failed (HTTP %s)", response.status_code)
            return None

        try:
            result = response.json()
        except ValueError:
            logger.error("Database returned invalid JSON (HTTP %s)", response.status_code)
            raise
        if response_model:
            try:
                result = response_model(**result)
            except Exception as e:
                logger.error("Database operation get_document_info: invalid response model (%s)", type(e).__name__)
                return None

        return result

    def get_page_info(self, document_id, page_id, library, route="/api/v1/pages/lookup", response_model=None):
        """Get page info through the PeopleGatorApp API.

        Args:
            document_id: Document identifier within the library.
            page_id: Page identifier (app source ID for image/layout uploads).
            library: Library identifier used for app document lookup.
            route: API route template; defaults to the operation's app endpoint.
            response_model: Optional Pydantic response class; None returns decoded JSON.

        Returns:
            Decoded JSON or the requested response model; None on an unsuccessful status or model-validation failure.

        Raises:
            ValueError: If an otherwise successful response contains invalid JSON.
        """
        url = self.compose_url(route)
        params = {
            "library": library,
            "document_id": str(document_id),
            "page_id": str(page_id),
        }

        response = self.connector.get(url, params=params)

        if response.status_code != HTTPStatus.OK:
            log = logger.debug if response.status_code == HTTPStatus.NOT_FOUND else logger.warning
            log("Database operation get_page_info failed (HTTP %s)", response.status_code)
            return None

        try:
            result = response.json()
        except ValueError:
            logger.error("Database returned invalid JSON (HTTP %s)", response.status_code)
            raise
        if response_model:
            try:
                result = response_model(**result)
            except Exception as e:
                logger.error("Database operation get_page_info: invalid response model (%s)", type(e).__name__)
                return None

        return result

    def get_faces_for_page(self, source_id, route="/api/v1/faces", response_model=None):
        """Get faces for page through the PeopleGatorApp API.

        Args:
            source_id: App source identifier for a page or document.
            route: API route template; defaults to the operation's app endpoint.
            response_model: Optional Pydantic response class; None returns decoded JSON.

        Returns:
            Decoded JSON or the requested response model; None on an unsuccessful status or model-validation failure.

        Raises:
            ValueError: If an otherwise successful response contains invalid JSON.
        """
        url = self.compose_url(route)
        params = {
            "filter.source_id": str(source_id),
            "limit": 1_000_000,
        }

        response = self.connector.get(url, params=params)

        if response.status_code != HTTPStatus.OK:
            logger.warning("Database operation get_faces_for_page failed (HTTP %s)", response.status_code)
            return None

        try:
            result = response.json()
        except ValueError:
            logger.error("Database returned invalid JSON (HTTP %s)", response.status_code)
            raise
        if response_model:
            try:
                result = response_model(**result)
            except Exception as e:
                logger.error("Database operation get_faces_for_page: invalid response model (%s)", type(e).__name__)
                return None

        return result

    def get_text_mentions_for_page(self, source_id, route="/api/v1/text-mentions", response_model=None):
        """Get text mentions for page through the PeopleGatorApp API.

        Args:
            source_id: App source identifier for a page or document.
            route: API route template; defaults to the operation's app endpoint.
            response_model: Optional Pydantic response class; None returns decoded JSON.

        Returns:
            Decoded JSON or the requested response model; None on an unsuccessful status or model-validation failure.

        Raises:
            ValueError: If an otherwise successful response contains invalid JSON.
        """
        url = self.compose_url(route)
        params = {
            "filter.source_id": str(source_id),
            "limit": 1_000_000,
        }

        response = self.connector.get(url, params=params)

        if response.status_code != HTTPStatus.OK:
            logger.warning("Database operation get_text_mentions_for_page failed (HTTP %s)", response.status_code)
            return None

        try:
            result = response.json()
        except ValueError:
            logger.error("Database returned invalid JSON (HTTP %s)", response.status_code)
            raise
        if response_model:
            try:
                result = response_model(**result)
            except Exception as e:
                logger.error("Database operation get_text_mentions_for_page: invalid response model (%s)", type(e).__name__)
                return None

        return result

    def get_entities_for_page(self, source_id, route="/api/v1/entities", response_model=None):
        """Get entities for page through the PeopleGatorApp API.

        Args:
            source_id: App source identifier for a page or document.
            route: API route template; defaults to the operation's app endpoint.
            response_model: Optional Pydantic response class; None returns decoded JSON.

        Returns:
            Decoded JSON or the requested response model; None on an unsuccessful status or model-validation failure.

        Raises:
            ValueError: If an otherwise successful response contains invalid JSON.
        """
        url = self.compose_url(route)
        params = {
            "filter.source_id": str(source_id),
            "limit": 1_000_000,
        }

        response = self.connector.get(url, params=params)

        if response.status_code != HTTPStatus.OK:
            logger.warning("Database operation get_entities_for_page failed (HTTP %s)", response.status_code)
            return None

        try:
            result = response.json()
        except ValueError:
            logger.error("Database returned invalid JSON (HTTP %s)", response.status_code)
            raise
        if response_model:
            try:
                result = response_model(**result)
            except Exception as e:
                logger.error("Database operation get_entities_for_page: invalid response model (%s)", type(e).__name__)
                return None

        return result

    def get_text_mentions_for_document(self, source_id, route="/api/v1/text-mentions", response_model=None):
        """Get text mentions for document through the PeopleGatorApp API.

        Args:
            source_id: App source identifier for a page or document.
            route: API route template; defaults to the operation's app endpoint.
            response_model: Optional Pydantic response class; None returns decoded JSON.

        Returns:
            Decoded JSON or the requested response model; None on an unsuccessful status or model-validation failure.

        Raises:
            ValueError: If an otherwise successful response contains invalid JSON.
        """
        url = self.compose_url(route)
        params = {
            "filter.document_source_id": str(source_id),
            "limit": 1_000_000,
        }

        response = self.connector.get(url, params=params)

        if response.status_code != HTTPStatus.OK:
            logger.warning("Database operation get_text_mentions_for_document failed (HTTP %s)", response.status_code)
            return None

        try:
            result = response.json()
        except ValueError:
            logger.error("Database returned invalid JSON (HTTP %s)", response.status_code)
            raise
        if response_model:
            try:
                result = response_model(**result)
            except Exception as e:
                logger.error("Database operation get_text_mentions_for_document: invalid response model (%s)", type(e).__name__)
                return None

        return result

    def get_faces_for_document(self, source_id, route="/api/v1/faces", response_model=None):
        """Get faces for document through the PeopleGatorApp API.

        Args:
            source_id: App source identifier for a page or document.
            route: API route template; defaults to the operation's app endpoint.
            response_model: Optional Pydantic response class; None returns decoded JSON.

        Returns:
            Decoded JSON or the requested response model; None on an unsuccessful status or model-validation failure.

        Raises:
            ValueError: If an otherwise successful response contains invalid JSON.
        """
        url = self.compose_url(route)
        params = {
            "filter.document_source_id": str(source_id),
            "limit": 1_000_000,
        }

        response = self.connector.get(url, params=params)

        if response.status_code != HTTPStatus.OK:
            logger.warning("Database operation get_faces_for_document failed (HTTP %s)", response.status_code)
            return None

        try:
            result = response.json()
        except ValueError:
            logger.error("Database returned invalid JSON (HTTP %s)", response.status_code)
            raise
        if response_model:
            try:
                result = response_model(**result)
            except Exception as e:
                logger.error("Database operation get_faces_for_document: invalid response model (%s)", type(e).__name__)
                return None

        return result

    def get_entities_for_document(self, source_id, route="/api/v1/entities", response_model=None):
        """Get entities for document through the PeopleGatorApp API.

        Args:
            source_id: App source identifier for a page or document.
            route: API route template; defaults to the operation's app endpoint.
            response_model: Optional Pydantic response class; None returns decoded JSON.

        Returns:
            Decoded JSON or the requested response model; None on an unsuccessful status or model-validation failure.

        Raises:
            ValueError: If an otherwise successful response contains invalid JSON.
        """
        url = self.compose_url(route)
        params = {
            "filter.document_source_id": str(source_id),
            "limit": 1_000_000,
        }

        response = self.connector.get(url, params=params)

        if response.status_code != HTTPStatus.OK:
            logger.warning("Database operation get_entities_for_document failed (HTTP %s)", response.status_code)
            return None

        try:
            result = response.json()
        except ValueError:
            logger.error("Database returned invalid JSON (HTTP %s)", response.status_code)
            raise
        if response_model:
            try:
                result = response_model(**result)
            except Exception as e:
                logger.error("Database operation get_entities_for_document: invalid response model (%s)", type(e).__name__)
                return None

        return result

    def get_entity_info(self, entity_id, route="/api/v1/entities/{entity_id}", response_model=None):
        """Get entity info through the PeopleGatorApp API.

        Args:
            entity_id: App person identifier.
            route: API route template; defaults to the operation's app endpoint.
            response_model: Optional Pydantic response class; None returns decoded JSON.

        Returns:
            Decoded JSON or the requested response model; None on an unsuccessful status or model-validation failure.

        Raises:
            ValueError: If an otherwise successful response contains invalid JSON.
        """
        url = self.compose_url(route.format(entity_id=entity_id))

        response = self.connector.get(url)

        if response.status_code != HTTPStatus.OK:
            logger.warning("Database operation get_entity_info failed (HTTP %s)", response.status_code)
            return None

        try:
            result = response.json()
        except ValueError:
            logger.error("Database returned invalid JSON (HTTP %s)", response.status_code)
            raise
        if response_model:
            try:
                result = response_model(**result)
            except Exception as e:
                logger.error("Database operation get_entity_info: invalid response model (%s)", type(e).__name__)
                return None

        return result

    def get_document_pages(self, document_id, library, route="/api/v1/pages", response_model=None):
        """Get document pages through the PeopleGatorApp API.

        Args:
            document_id: Document identifier within the library.
            library: Library identifier used for app document lookup.
            route: API route template; defaults to the operation's app endpoint.
            response_model: Optional Pydantic response class; None returns decoded JSON.

        Returns:
            Decoded JSON or the requested response model; None on an unsuccessful status or model-validation failure.

        Raises:
            ValueError: If an otherwise successful response contains invalid JSON.
        """
        url = self.compose_url(route)
        params = {
            "filter.library": library,
            "filter.document_id": str(document_id),
            "limit": 1_000_000,
        }

        response = self.connector.get(url, params=params)

        if response.status_code != HTTPStatus.OK:
            logger.warning("Database operation get_document_pages failed (HTTP %s)", response.status_code)
            return None

        try:
            result = response.json()
        except ValueError:
            logger.error("Database returned invalid JSON (HTTP %s)", response.status_code)
            raise
        if response_model:
            try:
                result = response_model(**result)
            except Exception as e:
                logger.error("Database operation get_document_pages: invalid response model (%s)", type(e).__name__)
                return None

        return result

    def delete_face(self, detection_id, route="/api/v1/faces/{detection_id}", response_model=None):
        """Delete face through the PeopleGatorApp API.

        Args:
            detection_id: App face detection identifier.
            route: API route template; defaults to the operation's app endpoint.
            response_model: Compatibility argument; unused for deletion.

        Returns:
            True on success, False on failure.
        """
        url = self.compose_url(route.format(detection_id=detection_id))

        response = self.connector.delete(url)

        if response.status_code != HTTPStatus.NO_CONTENT:
            logger.warning("Database operation delete_face failed (HTTP %s)", response.status_code)
            return False

        return True

    def delete_document(self, source_id, route="/api/v1/documents/{source_id}", response_model=None):
        """Delete document through the PeopleGatorApp API.

        Args:
            source_id: App source identifier for a page or document.
            route: API route template; defaults to the operation's app endpoint.
            response_model: Compatibility argument; unused for deletion.

        Returns:
            True on success, False on failure.
        """
        url = self.compose_url(route.format(source_id=source_id))

        response = self.connector.delete(url)

        if response.status_code != HTTPStatus.NO_CONTENT:
            logger.warning("Database operation delete_document failed (HTTP %s)", response.status_code)
            return False

        return True

    def delete_page(self, source_id, route="/api/v1/pages/{source_id}", response_model=None):
        """Delete page through the PeopleGatorApp API.

        Args:
            source_id: App source identifier for a page or document.
            route: API route template; defaults to the operation's app endpoint.
            response_model: Compatibility argument; unused for deletion.

        Returns:
            True on success, False on failure.
        """
        url = self.compose_url(route.format(source_id=source_id))

        response = self.connector.delete(url)

        if response.status_code != HTTPStatus.NO_CONTENT:
            logger.warning("Database operation delete_page failed (HTTP %s)", response.status_code)
            return False

        return True

    def delete_document_annotations(self, document_id, library):
        """Delete document annotations through the PeopleGatorApp API.

        Args:
            document_id: Document identifier within the library.
            library: Library identifier used for app document lookup.

        Returns:
            True on success, False on failure.
        """
        db_document_pages = self.get_document_pages(document_id, library)
        if db_document_pages is None:
            logger.error('Failed to get pages for document_id %s in library %s. Cannot delete annotations.', document_id, library)
            return False

        for db_page in db_document_pages["items"]:
            page_id = db_page["page_id"]
            source_id = db_page["source_id"]

            db_faces = self.get_faces_for_page(source_id)
            if db_faces is None:
                logger.error('Failed to get faces for page %s in document %s. Cannot delete annotations.', page_id, document_id)
                continue

            for db_face in db_faces["items"]:
                detection_id = db_face["detection_id"]
                self.delete_face(detection_id)

        return True

    def merge_entities(self, target_entity_id, other_entity_ids, description=None, short_description=None, route="/api/v1/entities/{target_entity_id}:merge-batch", response_model=None):
        """Merge entities through the PeopleGatorApp API.

        Args:
            target_entity_id: App entity that receives merged records.
            other_entity_ids: App entity identifiers to merge into the target.
            description: Optional long person or cluster description.
            short_description: Optional concise person description.
            route: API route template; defaults to the operation's app endpoint.
            response_model: Optional Pydantic response class; None returns decoded JSON.

        Returns:
            Decoded JSON or the requested response model; None on an unsuccessful status or model-validation failure.

        Raises:
            ValueError: If an otherwise successful response contains invalid JSON.
        """
        url = self.compose_url(route.format(target_entity_id=target_entity_id))

        payload = {
            "source_entity_ids": other_entity_ids,
            "description": description,
            "short_description": short_description
        }

        response = self.connector.post(url, json=payload)

        if response.status_code != HTTPStatus.OK:
            logger.warning("Database operation merge_entities failed (HTTP %s)", response.status_code)
            return None

        try:
            result = response.json()
        except ValueError:
            logger.error("Database returned invalid JSON (HTTP %s)", response.status_code)
            raise
        if response_model:
            try:
                result = response_model(**result)
            except Exception as e:
                logger.error("Database operation merge_entities: invalid response model (%s)", type(e).__name__)
                return None

        return result
