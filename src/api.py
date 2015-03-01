import requests, lxml.html, re
from lxml import etree
from flask import Flask, request, jsonify
from caches.Cache import Cache

API_KEY = ""
with open("steam.key") as key:
    API_KEY = key.readline().replace("\n", "")

GAME_LIBRARY_CACHE = Cache()
GAME_INFO_CACHE = Cache()

def get_steam_id():
    """
    Gets a steam_id for a given custom url
    """
    vanity_url = request.args.get("vanity_url")
    if vanity_url is None:
        return create_error_json('You must provide vainty_url as a get parameter')
    endpoint = "http://api.steampowered.com/ISteamUser/ResolveVanityURL/v0001/?key=%s&vanityurl=%s"%(API_KEY, vanity_url)
    r = requests.get(endpoint)
    response = r.json()["response"]
    if response["success"] is not 1:
        return create_error_json('A user with url %s was not found (message: %s)'%(vanity_url, response["message"]))
    return jsonify({'steam_id':response['steamid'], 'success':True})

def get_friend_list():
    """
    Gets the steam_ids of all friends associated with steam_id
    """
    steam_id = request.args.get('steam_id')
    errors = find_invalid(steam_id)
    if errors is not None:
        return errors
    endpoint = 'http://api.steampowered.com/ISteamUser/GetFriendList/v0001/?key=%s&steamid=%s&relationship=friend'%(API_KEY, steam_id)
    raw_response = requests.get(endpoint)
    friends = {'friends': [{'steam_id':x['steamid'], 'since': x['friend_since']} for x in raw_response.json()['friendslist']['friends']], "success":True}
    return jsonify(friends)

def get_games():
    """
    Gets all game appid's associated with steam_id
    """
    steam_id = request.args.get('steam_id')
    errors = find_invalid(steam_id)
    if errors is not None:
        return errors
    return jsonify(get_games_request(steam_id))


def get_games_request(steam_id):
    """
    Performs the REST request to get the games of user <steam_id>
    Returns the json for total games, and a list of games and forever_playtime
    """
    all_games = GAME_LIBRARY_CACHE.get(steam_id)
    if all_games is None:
        endpoint = "http://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/?key=%s&steamid=%s&format=json"%(API_KEY, steam_id)
        raw_response = requests.get(endpoint)
        if raw_response.status_code is not 200:
            return create_error_json('There was an unexpected api error'), raw_response.status_code
        all_games = raw_response.json()["response"]
        all_games['success'] = True
        all_games["games"] = [{"app_id":game["appid"], "playtime_forever":game["playtime_forever"]} for game in all_games["games"]]
        GAME_LIBRARY_CACHE.set(steam_id, all_games)
    return all_games

def get_info_for_game():
    """
    Returns the game schema for a game with associated appid.
    """
    app_id = request.args.get('app_id')
    game_info = GAME_INFO_CACHE.get(app_id)
    if game_info is None:
        #TODO: This is technically the right way to do this, but the steam API is a little busted.
        # endpoint = "http://api.steampowered.com/ISteamUserStats/GetSchemaForGame/v2/?key=%s&appid=%s"%(API_KEY, app_id)
        # raw_response = requests.get(endpoint)
        # game_info = raw_response.json()
        #TODO: So we're going to do it the wrong way... HTML PARSING GO!!
        store_page = lxml.html.parse("http://store.steampowered.com/app/%s"%app_id)
        title = store_page.find(".//title").text.replace(" on Steam", "")
        img = store_page.find(".//div[@class='game_header_image_ctn']/img")
        image_tag = etree.tostring(img).replace("&#13;", "").rstrip("\t").rstrip("\n")
        game_info = {"title":title, "image":image_tag}
        GAME_INFO_CACHE.set(app_id, game_info)
    return jsonify({"game":game_info, "success":True})

def create_error_json(message):
    """
    Boiler plate for creating an error json blob.
    """
    return jsonify({'message':message,'success':False})

def find_invalid(steam_id):
    """
    Validates a steam id. Returns None if everything is okay, or error json if somethign is awry.
    """
    if steam_id is None:
        return create_error_json('Steam id must be provided.')
    if len(steam_id) is not 17:
        return create_error_json('Steam id is the incorrect length (%d) must be 17 numbers'%len(steam_id))
    m = re.search('7656119[0-9]{10}$', steam_id)
    if m is None:
        return create_error_json('Steam id (%s) is not numeric only.'%steam_id)
    return None
