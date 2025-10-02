
# All Rights Reserved.
# Issued under the Academic Public License.
#
# You can be released from the terms, and requirements of the Academic Public
# License by purchasing a commercial license.
# Purchase of a commercial license is mandatory for any use of the
# neuro-san SDK Software in commercial settings.
#
# END COPYRIGHT
from typing import Any
from typing import Dict

from leaf_common.serialization.interface.dictionary_converter import DictionaryConverter

from neuro_san.interfaces.reservation import Reservation


class ReservationDictionaryConverter(DictionaryConverter):
    """
    DictionaryConverter implementation for converting Reservations back and forth to dictionaries.
    """

    def to_dict(self, obj: Reservation) -> Dict[str, Any]:
        """
        :param obj: The Reservation object to be converted into a dictionary
        :return: A data-only dictionary that represents all the data for
                the given object, either in primitives
                (booleans, ints, floats, strings), arrays, or dictionaries.
                If obj is None, then the returned dictionary should also be
                None.  If obj is not the correct type, it is also reasonable
                to return None.
        """
        reservation: Reservation = obj

        obj_dict: Dict[str, Any] = {
            "id": reservation.get_reservation_id(),
            "lifetime_in_seconds": reservation.get_lifetime_in_seconds(),
            "expiration_time_in_seconds": reservation.get_expiration_time_in_seconds()
        }

        return obj_dict

    def from_dict(self, obj_dict: Dict[str, Any]) -> Reservation:
        """
        :param obj_dict: The data-only dictionary to be converted into an object
        :return: An object instance created from the given dictionary.
                If obj_dict is None, the returned object should also be None.
                If obj_dict is not the correct type, it is also reasonable
                to return None.
        """
        reservation = Reservation(obj_dict.get("lifetime_in_seconds"))
        reservation.id = obj_dict.get("id")
        reservation.expiration_time_in_seconds = obj_dict.get("expiration_time_in_seconds")

        return reservation
