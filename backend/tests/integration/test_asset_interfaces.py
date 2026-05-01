"""
Integration tests for Asset Generation Interfaces.

Tests the asset generation interfaces for portraits, scenes, and audio.
"""

import pytest
import asyncio
from datetime import datetime

from llm_rpg.assets import (
    AssetProvider,
    AssetGenerationRequest,
    AssetGenerationResult,
    AssetType,
    AssetStatus,
)
from llm_rpg.assets.portrait import (
    PortraitGenerator,
    PortraitRequest,
    PortraitResult,
    PortraitStyle,
    PortraitExpression,
    MockPortraitGenerator,
)
from llm_rpg.assets.scene import (
    SceneGenerator,
    SceneRequest,
    SceneResult,
    TimeOfDay,
    WeatherCondition,
    ArtStyle,
    MockSceneGenerator,
)
from llm_rpg.assets.audio import (
    AudioGenerator,
    BGMRequest,
    BGMResult,
    SFXRequest,
    SFXResult,
    MusicMood,
    MusicGenre,
    SFXType,
    MockAudioGenerator,
)


class TestAssetInterfacesBase:
    """Tests for base asset interfaces."""
    
    @pytest.mark.asyncio
    async def test_mock_asset_provider_generate(self):
        """Test mock asset provider generate method."""
        provider = MockPortraitGenerator()
        
        request = PortraitRequest(
            asset_type=AssetType.PORTRAIT,
            request_id="test_001",
            npc_id="npc_001",
            npc_name="Test NPC",
            style=PortraitStyle.ANIME,
        )
        
        result = await provider.generate(request)
        
        assert result is not None
        assert result.request_id == "test_001"
        assert result.asset_id is not None
        assert result.status == AssetStatus.COMPLETED.value
        assert result.image_url is not None
    
    @pytest.mark.asyncio
    async def test_mock_asset_provider_check_status(self):
        """Test mock asset provider status check."""
        provider = MockPortraitGenerator()
        
        request = PortraitRequest(
            asset_type=AssetType.PORTRAIT,
            request_id="test_002",
            npc_id="npc_002",
            npc_name="Test NPC",
        )
        
        result = await provider.generate(request)
        status = await provider.check_status("test_002")
        
        assert status == AssetStatus.COMPLETED
    
    @pytest.mark.asyncio
    async def test_mock_asset_provider_cancel(self):
        """Test mock asset provider cancel method."""
        provider = MockPortraitGenerator()
        
        request = PortraitRequest(
            asset_type=AssetType.PORTRAIT,
            request_id="test_003",
            npc_id="npc_003",
            npc_name="Test NPC",
        )
        
        result = await provider.generate(request)
        cancelled = await provider.cancel("test_003")
        
        assert cancelled is False
    
    def test_asset_provider_info(self):
        """Test getting provider information."""
        provider = MockPortraitGenerator()
        
        info = provider.get_provider_info()
        
        assert "provider_name" in info
        assert "supported_types" in info
        assert AssetType.PORTRAIT.value in info["supported_types"]
    
    def test_asset_provider_supports(self):
        """Test checking if provider supports asset type."""
        provider = MockPortraitGenerator()
        
        supports_portrait = provider.supports(AssetType.PORTRAIT)
        supports_scene = provider.supports(AssetType.SCENE)
        
        assert supports_portrait is True
        assert supports_scene is False


class TestPortraitGenerator:
    """Tests for portrait generation interface."""
    
    @pytest.mark.asyncio
    async def test_generate_portrait(self):
        """Test generating a portrait."""
        generator = MockPortraitGenerator()
        
        request = PortraitRequest(
            asset_type=AssetType.PORTRAIT,
            request_id="portrait_001",
            npc_id="npc_elder",
            npc_name="Elder NPC",
            npc_description="An old wise character",
            npc_personality=["wise", "calm", "helpful"],
            style=PortraitStyle.ANIME,
            expression=PortraitExpression.NEUTRAL,
        )
        
        result = await generator.generate_portrait(request)
        
        assert result is not None
        assert isinstance(result, PortraitResult)
        assert result.npc_id == "npc_elder"
        assert result.style == PortraitStyle.ANIME
        assert result.expression == PortraitExpression.NEUTRAL
        assert result.image_url is not None
        assert result.thumbnail_url is not None
        assert "mock" in result.image_url
    
    @pytest.mark.asyncio
    async def test_generate_portrait_variations(self):
        """Test generating portrait variations."""
        generator = MockPortraitGenerator()
        
        request = PortraitRequest(
            asset_type=AssetType.PORTRAIT,
            request_id="portrait_002",
            npc_id="npc_warrior",
            npc_name="Warrior NPC",
            style=PortraitStyle.REALISTIC,
            expression=PortraitExpression.DETERMINED,
        )
        
        variations = await generator.generate_variations(request, num_variations=4)
        
        assert len(variations) == 4
        for variation in variations:
            assert variation.npc_id == "npc_warrior"
            assert variation.style == PortraitStyle.REALISTIC
    
    @pytest.mark.asyncio
    async def test_modify_expression(self):
        """Test modifying portrait expression."""
        generator = MockPortraitGenerator()
        
        modified = await generator.modify_expression(
            base_portrait_id="portrait_base_001",
            new_expression=PortraitExpression.HAPPY,
        )
        
        assert modified is not None
        assert modified.expression == PortraitExpression.HAPPY
        assert "happy" in modified.image_url
    
    @pytest.mark.asyncio
    async def test_portrait_styles(self):
        """Test all portrait styles are supported."""
        generator = MockPortraitGenerator()
        
        for style in PortraitStyle:
            request = PortraitRequest(
                asset_type=AssetType.PORTRAIT,
                request_id=f"portrait_style_{style.value}",
                npc_id="npc_test",
                style=style,
            )
            result = await generator.generate_portrait(request)
            assert result.style == style
    
    @pytest.mark.asyncio
    async def test_portrait_expressions(self):
        """Test all portrait expressions are supported."""
        generator = MockPortraitGenerator()
        
        for expression in PortraitExpression:
            request = PortraitRequest(
                asset_type=AssetType.PORTRAIT,
                request_id=f"portrait_expr_{expression.value}",
                npc_id="npc_test",
                expression=expression,
            )
            result = await generator.generate_portrait(request)
            assert result.expression == expression


class TestSceneGenerator:
    """Tests for scene generation interface."""
    
    @pytest.mark.asyncio
    async def test_generate_scene(self):
        """Test generating a scene."""
        generator = MockSceneGenerator()
        
        request = SceneRequest(
            asset_type=AssetType.SCENE,
            request_id="scene_001",
            location_id="loc_forest",
            location_name="Mystic Forest",
            location_description="A dense magical forest",
            time_of_day=TimeOfDay.DUSK,
            weather=WeatherCondition.FOGGY,
            art_style=ArtStyle.CONCEPT_ART,
        )
        
        result = await generator.generate_scene(request)
        
        assert result is not None
        assert isinstance(result, SceneResult)
        assert result.location_id == "loc_forest"
        assert result.time_of_day == TimeOfDay.DUSK
        assert result.weather == WeatherCondition.FOGGY
        assert result.image_url is not None
        assert result.width == 1024
        assert result.height == 768
    
    @pytest.mark.asyncio
    async def test_generate_time_variations(self):
        """Test generating scene at different times."""
        generator = MockSceneGenerator()
        
        request = SceneRequest(
            asset_type=AssetType.SCENE,
            request_id="scene_time_001",
            location_id="loc_castle",
            location_name="Castle",
            time_of_day=TimeOfDay.DAY,
        )
        
        times = [TimeOfDay.DAWN, TimeOfDay.DAY, TimeOfDay.DUSK]
        variations = await generator.generate_time_variations(request, times=times)
        
        assert len(variations) == 3
        for i, variation in enumerate(variations):
            assert variation.time_of_day == times[i]
    
    @pytest.mark.asyncio
    async def test_generate_weather_variations(self):
        """Test generating scene in different weather."""
        generator = MockSceneGenerator()
        
        request = SceneRequest(
            asset_type=AssetType.SCENE,
            request_id="scene_weather_001",
            location_id="loc_mountain",
            location_name="Mountain Peak",
            weather=WeatherCondition.CLEAR,
        )
        
        weather_conditions = [WeatherCondition.CLEAR, WeatherCondition.CLOUDY, WeatherCondition.STORMY]
        variations = await generator.generate_weather_variations(
            request, weather_conditions=weather_conditions
        )
        
        assert len(variations) == 3
        for i, variation in enumerate(variations):
            assert variation.weather == weather_conditions[i]
    
    @pytest.mark.asyncio
    async def test_all_times_of_day(self):
        """Test all times of day are supported."""
        generator = MockSceneGenerator()
        
        for time in TimeOfDay:
            request = SceneRequest(
                asset_type=AssetType.SCENE,
                request_id=f"scene_time_{time.value}",
                location_id="loc_test",
                time_of_day=time,
            )
            result = await generator.generate_scene(request)
            assert result.time_of_day == time
    
    @pytest.mark.asyncio
    async def test_all_weather_conditions(self):
        """Test all weather conditions are supported."""
        generator = MockSceneGenerator()
        
        for weather in WeatherCondition:
            request = SceneRequest(
                asset_type=AssetType.SCENE,
                request_id=f"scene_weather_{weather.value}",
                location_id="loc_test",
                weather=weather,
            )
            result = await generator.generate_scene(request)
            assert result.weather == weather


class TestAudioGenerator:
    """Tests for audio generation interface."""
    
    @pytest.mark.asyncio
    async def test_generate_bgm(self):
        """Test generating background music."""
        generator = MockAudioGenerator()
        
        request = BGMRequest(
            asset_type=AssetType.BGM,
            request_id="bgm_001",
            location_id="loc_tavern",
            location_name="Tavern",
            mood=MusicMood.JOYFUL,
            genre=MusicGenre.FOLK,
            duration_seconds=120,
            loopable=True,
        )
        
        result = await generator.generate_bgm(request)
        
        assert result is not None
        assert isinstance(result, BGMResult)
        assert result.mood == MusicMood.JOYFUL
        assert result.genre == MusicGenre.FOLK
        assert result.duration_seconds == 120
        assert result.audio_url is not None
        assert result.loop_start_seconds == 0.0
        assert result.loop_end_seconds == 120.0
    
    @pytest.mark.asyncio
    async def test_generate_sfx(self):
        """Test generating sound effect."""
        generator = MockAudioGenerator()
        
        request = SFXRequest(
            asset_type=AssetType.SFX,
            request_id="sfx_001",
            sfx_type=SFXType.DOOR_OPEN,
            description="Wooden door opening",
            duration_seconds=2,
            volume_db=-5.0,
        )
        
        result = await generator.generate_sfx(request)
        
        assert result is not None
        assert isinstance(result, SFXResult)
        assert result.sfx_type == SFXType.DOOR_OPEN
        assert result.duration_seconds == 2
        assert result.audio_url is not None
        assert "door_open" in result.audio_url
    
    @pytest.mark.asyncio
    async def test_generate_sfx_batch(self):
        """Test generating multiple sound effects."""
        generator = MockAudioGenerator()
        
        requests = [
            SFXRequest(
                asset_type=AssetType.SFX,
                request_id=f"sfx_batch_{i}",
                sfx_type=sfx_type,
            )
            for i, sfx_type in enumerate([SFXType.UI_CLICK, SFXType.STEP, SFXType.COMBAT_HIT])
        ]
        
        results = await generator.generate_sfx_batch(requests)
        
        assert len(results) == 3
        assert all(isinstance(r, SFXResult) for r in results)
    
    @pytest.mark.asyncio
    async def test_extend_bgm(self):
        """Test extending existing background music."""
        generator = MockAudioGenerator()
        
        extended = await generator.extend_bgm(
            existing_bgm_id="bgm_original_001",
            additional_duration_seconds=60,
        )
        
        assert extended is not None
        assert extended.duration_seconds == 60
        assert "extended" in extended.audio_url
    
    @pytest.mark.asyncio
    async def test_all_music_moods(self):
        """Test all music moods are supported."""
        generator = MockAudioGenerator()
        
        for mood in MusicMood:
            request = BGMRequest(
                asset_type=AssetType.BGM,
                request_id=f"bgm_mood_{mood.value}",
                mood=mood,
            )
            result = await generator.generate_bgm(request)
            assert result.mood == mood
    
    @pytest.mark.asyncio
    async def test_all_sfx_types(self):
        """Test all SFX types are supported."""
        generator = MockAudioGenerator()
        
        for sfx_type in SFXType:
            request = SFXRequest(
                asset_type=AssetType.SFX,
                request_id=f"sfx_type_{sfx_type.value}",
                sfx_type=sfx_type,
            )
            result = await generator.generate_sfx(request)
            assert result.sfx_type == sfx_type


class TestAssetGenerationIntegration:
    """Integration tests for asset generation workflow."""
    
    @pytest.mark.asyncio
    async def test_complete_npc_assets(self):
        """Test generating complete set of assets for an NPC."""
        portrait_gen = MockPortraitGenerator()
        
        base_request = PortraitRequest(
            asset_type=AssetType.PORTRAIT,
            request_id="npc_complete_001",
            npc_id="npc_merchant",
            npc_name="Merchant",
            style=PortraitStyle.ANIME,
            expression=PortraitExpression.NEUTRAL,
        )
        
        base_portrait = await portrait_gen.generate_portrait(base_request)
        
        expressions = [PortraitExpression.HAPPY, PortraitExpression.ANGRY]
        for expression in expressions:
            await portrait_gen.modify_expression(base_portrait.asset_id, expression)
        
        assert base_portrait is not None
        assert base_portrait.image_url is not None
    
    @pytest.mark.asyncio
    async def test_complete_location_assets(self):
        """Test generating complete set of assets for a location."""
        scene_gen = MockSceneGenerator()
        
        base_request = SceneRequest(
            asset_type=AssetType.SCENE,
            request_id="loc_complete_001",
            location_id="loc_village",
            location_name="Village Square",
            art_style=ArtStyle.PAINTED,
        )
        
        time_variations = await scene_gen.generate_time_variations(base_request)
        weather_variations = await scene_gen.generate_weather_variations(base_request)
        
        assert len(time_variations) == 5
        assert len(weather_variations) == 6
    
    @pytest.mark.asyncio
    async def test_audio_suite_for_scene(self):
        """Test generating audio suite for a scene."""
        audio_gen = MockAudioGenerator()
        
        bgm_request = BGMRequest(
            asset_type=AssetType.BGM,
            request_id="scene_audio_bgm_001",
            location_name="Dungeon",
            mood=MusicMood.DARK,
            duration_seconds=180,
        )
        bgm = await audio_gen.generate_bgm(bgm_request)
        
        sfx_types = [
            SFXType.DOOR_OPEN,
            SFXType.STEP,
            SFXType.AMBIENT_WIND,
        ]
        sfx_requests = [
            SFXRequest(
                asset_type=AssetType.SFX,
                request_id=f"scene_audio_sfx_{i}",
                sfx_type=sfx_type,
            )
            for i, sfx_type in enumerate(sfx_types)
        ]
        sfx_results = await audio_gen.generate_sfx_batch(sfx_requests)
        
        assert bgm is not None
        assert len(sfx_results) == 3


class TestMediaAPIIntegration:
    """Tests for media API endpoint integration."""
    
    def test_media_request_models(self):
        """Test that media API request models are compatible."""
        from llm_rpg.api.media import (
            PortraitGenerateRequest,
            SceneGenerateRequest,
            BGMGenerateRequest,
        )
        
        portrait_req = PortraitGenerateRequest(
            npc_id="npc_001",
            style="anime",
            expression="neutral",
        )
        
        scene_req = SceneGenerateRequest(
            location_id="loc_001",
            time_of_day="day",
        )
        
        bgm_req = BGMGenerateRequest(
            location_id="loc_001",
            mood="calm",
        )
        
        assert portrait_req.npc_id == "npc_001"
        assert scene_req.location_id == "loc_001"
        assert bgm_req.mood == "calm"
    
    def test_media_response_models(self):
        """Test that media API response models are defined."""
        from llm_rpg.api.media import (
            PortraitGenerateResponse,
            SceneGenerateResponse,
            BGMGenerateResponse,
        )
        
        portrait_resp = PortraitGenerateResponse(
            portrait_id="portrait_001",
            npc_id="npc_001",
            image_url="https://example.com/portrait.png",
            style="anime",
            status="completed",
        )
        
        assert portrait_resp.portrait_id == "portrait_001"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
