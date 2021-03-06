import requests, re
from flask import Flask, request, jsonify
from caches.Cache import Cache
from os import environ
from urllib.parse import quote
from bs4 import BeautifulSoup

API_KEY = ""
try:
    API_KEY = environ['STEAM_KEY']
    print ("Using environment variable for key.")
except KeyError:
    with open("steam.key") as key:
        API_KEY = key.readline().replace("\n", "")
    print ("Using file for key")

GAME_LIBRARY_CACHE = Cache()
GAME_INFO_CACHE = Cache()
PROFILE_INFO_CACHE = Cache()

def get_steam_id():
    """
    Gets a steam_id for a given custom url
    """
    vanity_url = request.args.get("vanity_url")
    if vanity_url is None:
        return create_error_json('You must provide vainty_url as a get parameter')
    endpoint = "http://api.steampowered.com/ISteamUser/ResolveVanityURL/v0001/?key=%s&vanityurl=%s"%(API_KEY, quote(vanity_url))
    json = requests.get(endpoint).json()
    if not json:
        return create_error_json("No user found by vanity url %s"%vanity_url)
    response = json["response"]
    if response["success"] is not 1:
        return create_error_json('A user with url %s was not found (message: %s)'%(vanity_url, response["message"]))
    return jsonify({'steam_id':response['steamid'], 'success':True})

def get_profile():
    """
    Gets a persona name, and avatar for a given steam id
    """
    steam_id = request.args.get("steam_id")
    errors = find_invalid(steam_id)
    if errors is not None:
        return errors
    profile = PROFILE_INFO_CACHE.get(steam_id)
    if profile is None:
        refresh_cache_for_profiles([steam_id])
        profile = PROFILE_INFO_CACHE.get(steam_id)
    if profile is not {}:
        return jsonify({'success':True, "profile":profile})
    else:
        return create_error_json("Could not find a profile for steam id %s"%steam_id)

def get_profiles():
    steam_ids = request.args.get("steam_ids").split(",")
    for steam_id in steam_ids:
        bad_steam_id = find_invalid(steam_id)
        if bad_steam_id is not None:
            return bad_steam_id
    cached = {"%s"%steam_id : PROFILE_INFO_CACHE.get("%s"%steam_id) for steam_id in steam_ids}
    to_retrieve = []
    for steam_id, cached_value in cached.items():
        if cached_value is None:
            to_retrieve.append(steam_id)
    if len(to_retrieve) is not 0:
        refresh_cache_for_profiles(to_retrieve)
    cached = {"%s"%steam_id : PROFILE_INFO_CACHE.get("%s"%steam_id) for steam_id in steam_ids}
    return jsonify({"success":True, "profiles": [profile for profile in cached.values()]})

def refresh_cache_for_profiles(steam_ids_to_get):
    endpoint = "http://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/?key=%s&steamids=%s"%(API_KEY, ",".join(steam_ids_to_get))
    raw_response = requests.get(endpoint)
    profile_info = raw_response.json()["response"]["players"]
    if len(profile_info) is not 0:
        for profile in profile_info:
            if "realname" not in profile:
                profile["realname"] = None
        profiles = [ {"avatar_full":info["avatarfull"], "avatar_medium":info["avatarmedium"], "persona_name":info["personaname"], "real_name":info["realname"], "steam_id":info["steamid"]} for info in profile_info]
        for profile in profiles:
            PROFILE_INFO_CACHE.set(profile["steam_id"], profile)
    else:
        for steam_id in steam_ids_to_get:
            PROFILE_INFO_CACHE.set(steam_id, {})
    pass

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
        try:
            all_games["games"] = [{"app_id":game["appid"], "playtime_forever":game["playtime_forever"]} for game in all_games["games"]]
        except(KeyError):
            return create_error_json('User has no games, or profile is set to private.', False)
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
        url = 'http://store.steampowered.com/app/%s'%app_id
        page = requests.get(url, stream=True)
        if len(page.history) is not 0: #this is an age check.
            print("Age gate detected on app id:  " + str(app_id))
            cookies = {'sessionid': page.cookies['sessionid'], 'birthtime':'631180801', 'lastagecheckage':'1-January-1990'}
            page = requests.get(url, cookies=cookies, stream=True)

        store_page = BeautifulSoup(page.text.encode('utf-8'), 'html.parser')
        try:
            title = store_page.find("div", class_="apphub_AppName").text
        except AttributeError:
            title = store_page.find("title").text.replace(" on Steam", "")
        title = ''.join([x for x in title if ord(x) != 194])
        specs = store_page.find_all("div", class_="game_area_details_specs")
        categories = []
        if specs is not None:
            for spec in specs:
                links = spec.find_all("a")
                for link in links:
                    categories.append(link)
        else:
            print ("Could not find any specs for app: " + app_id)

        is_multiplayer = False
        for attrib in categories:
            attrib_text = attrib.encode('utf-8').decode('utf-8')
            is_multiplayer = "Multi-player" in attrib_text or "Co-op" in attrib_text
            if is_multiplayer:
                break
        image_tag = "<img src='http://cdn.akamai.steamstatic.com/steam/apps/%s/header.jpg' />"%app_id
        game_info = {"title":title, "image":image_tag, "is_multiplayer":is_multiplayer}
        GAME_INFO_CACHE.set(app_id, game_info)
    return jsonify({"game":game_info, "success":True})

def create_error_json(message, should_jsonify=True):
    """
    Boiler plate for creating an error json blob.
    """
    error = {'message':message,'success':False}
    if should_jsonify is True:
        return jsonify(error)
    return error

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
